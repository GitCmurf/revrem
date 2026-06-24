"""Textual-free live-run process controller for the optional TUI."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal

from code_review_loop import profiles, tui_state
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity

RunControllerStatus = Literal[
    "idle",
    "starting",
    "running",
    "completed-clear",
    "completed-findings",
    "budget",
    "setup-failed",
    "cancelled",
    "interrupted-before-run-initialized",
    "failed",
]

PopenFactory = Callable[..., subprocess.Popen[str]]
EntrypointResolver = Callable[[Sequence[str]], list[str]]


@dataclass(frozen=True)
class LiveRunLaunch:
    argv: tuple[str, ...]
    artifact_dir_arg: str
    artifact_dir: Path


@dataclass
class _BoundedLines:
    max_lines: int = 200
    _lines: list[str] = field(default_factory=list)

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self._lines)

    def append(self, line: str) -> None:
        self._lines.append(line)
        if len(self._lines) > self.max_lines:
            del self._lines[: len(self._lines) - self.max_lines]


@dataclass
class LiveRunController:
    status: RunControllerStatus = "idle"
    process: subprocess.Popen[str] | None = None
    launch: LiveRunLaunch | None = None
    exit_code: int | None = None
    message: str | None = None
    stdout_tail: tuple[str, ...] = ()
    stderr_tail: tuple[str, ...] = ()
    _stdout_buffer: _BoundedLines = field(default_factory=_BoundedLines)
    _stderr_buffer: _BoundedLines = field(default_factory=_BoundedLines)
    _drain_threads: list[threading.Thread] = field(default_factory=list)

    def start(
        self,
        *,
        profile: profiles.Profile,
        plan: tui_state.LaunchPlan,
        cwd: Path,
        entrypoint_resolver: EntrypointResolver,
        popen_factory: PopenFactory = subprocess.Popen,
        identity: RunIdentity = SYSTEM_IDENTITY,
    ) -> LiveRunLaunch:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("a live run is already active")
        launch = prepare_live_run_launch(profile=profile, plan=plan, cwd=cwd, identity=identity)
        argv = entrypoint_resolver(launch.argv)
        self.status = "starting"
        self.launch = launch
        self.exit_code = None
        self.message = None
        self._stdout_buffer = _BoundedLines()
        self._stderr_buffer = _BoundedLines()
        self.process = popen_factory(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self._drain_threads = [
            _drain_stream(self.process.stdout, self._stdout_buffer, name="revrem-tui-stdout"),
            _drain_stream(self.process.stderr, self._stderr_buffer, name="revrem-tui-stderr"),
        ]
        self.status = "running"
        return launch

    def refresh(self) -> RunControllerStatus:
        if self.process is None:
            return self.status
        exit_code = self.process.poll()
        if exit_code is None:
            return self.status
        return self.finish(exit_code)

    def finish(self, exit_code: int | None = None) -> RunControllerStatus:
        if self.process is None:
            return self.status
        if exit_code is None:
            exit_code = self.process.wait()
        for thread in self._drain_threads:
            thread.join(timeout=1)
        self.exit_code = exit_code
        self.stdout_tail = self._stdout_buffer.lines
        self.stderr_tail = self._stderr_buffer.lines
        summary = self._read_summary()
        self.status = classify_exit(exit_code, summary=summary)
        if summary is None and exit_code != 0:
            detail = "\n".join((*self.stderr_tail, *self.stdout_tail)).strip()
            self.message = detail or f"run exited with code {exit_code} before writing summary.json"
        return self.status

    def _read_summary(self) -> dict[str, object] | None:
        if self.launch is None:
            return None
        summary_path = self.launch.artifact_dir / "summary.json"
        if not summary_path.is_file():
            return None
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def prepare_live_run_launch(
    *,
    profile: profiles.Profile,
    plan: tui_state.LaunchPlan,
    cwd: Path,
    identity: RunIdentity = SYSTEM_IDENTITY,
) -> LiveRunLaunch:
    artifact_dir_arg = profile.output.artifact_dir or str(default_live_artifact_dir(identity=identity))
    artifact_dir = _resolve_child_path(artifact_dir_arg, cwd=cwd)
    argv = (
        *plan.argv,
        "--artifact-dir",
        artifact_dir_arg,
        "--no-tty",
        "--pending-review",
        "ignore",
        "--summary-format",
        "json",
    )
    return LiveRunLaunch(
        argv=tuple(argv),
        artifact_dir_arg=artifact_dir_arg,
        artifact_dir=artifact_dir,
    )


def default_live_artifact_dir(*, identity: RunIdentity = SYSTEM_IDENTITY) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".revrem") / "runs" / f"{timestamp}-{identity.new_run_id()}"


def classify_exit(
    exit_code: int,
    *,
    summary: dict[str, object] | None = None,
) -> RunControllerStatus:
    final_status = str(summary.get("final_status") or "") if summary else ""
    stopped_reason = str(summary.get("stopped_reason") or "") if summary else ""
    if exit_code == 0:
        return "completed-clear"
    if exit_code == 2:
        return "completed-findings"
    if exit_code == 3:
        return "budget"
    if exit_code == 4:
        return "setup-failed"
    if exit_code == 5 and final_status == "error" and stopped_reason == "cancelled":
        return "cancelled"
    if exit_code == 130 and summary is None:
        return "interrupted-before-run-initialized"
    return "failed"


def _resolve_child_path(path: str, *, cwd: Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return cwd / resolved


def _drain_stream(
    stream: IO[str] | None,
    buffer: _BoundedLines,
    *,
    name: str,
) -> threading.Thread:
    def run() -> None:
        if stream is None:
            return
        try:
            for line in stream:
                buffer.append(line.rstrip("\n"))
        finally:
            stream.close()

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread

