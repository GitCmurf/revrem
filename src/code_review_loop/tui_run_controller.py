"""Textual-free live-run process controller for the optional TUI."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal

from code_review_loop import events, profiles, tui_state
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
    "failed-forced-cleanup",
]
TERMINAL_STATUSES: frozenset[RunControllerStatus] = frozenset(
    {
        "completed-clear",
        "completed-findings",
        "budget",
        "setup-failed",
        "cancelled",
        "interrupted-before-run-initialized",
        "failed",
        "failed-forced-cleanup",
    }
)

PopenFactory = Callable[..., subprocess.Popen[str]]
EntrypointResolver = Callable[[Sequence[str]], list[str]]


@dataclass(frozen=True)
class LiveRunLaunch:
    argv: tuple[str, ...]
    artifact_dir_arg: str
    artifact_dir: Path


@dataclass(frozen=True)
class LiveEventSnapshot:
    events: tuple[events.Event, ...] = ()
    truncated: bool = False
    error: str | None = None
    ready: bool = False


@dataclass(frozen=True)
class EventFileIdentity:
    inode: int | None
    size: int
    mtime_ns: int
    first_run_id: str | None


@dataclass(frozen=True)
class FileIdentity:
    inode: int | None
    size: int
    mtime_ns: int


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
    preexisting_events: EventFileIdentity | None = None
    preexisting_summary: FileIdentity | None = None
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
        self.preexisting_events = _event_file_identity(
            launch.artifact_dir / events.EVENTS_FILENAME
        )
        self.preexisting_summary = _file_identity(launch.artifact_dir / "summary.json")
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

    def cancel(self, *, grace_seconds: float = 5.0) -> RunControllerStatus:
        if self.process is None:
            return self.status
        if self.process.poll() is not None:
            return self.finish(self.process.returncode)
        descendant_pids = _descendant_pids(self.process)
        _signal_process_group(self.process, signal.SIGINT)
        try:
            status = self.finish(self.process.wait(timeout=grace_seconds))
            _terminate_descendants(descendant_pids, grace_seconds=grace_seconds)
            return status
        except subprocess.TimeoutExpired:
            _signal_process_group(self.process, signal.SIGTERM)
            _signal_process_groups_by_pid(descendant_pids, signal.SIGTERM)
        try:
            status = self.finish(self.process.wait(timeout=grace_seconds))
            _terminate_descendants(descendant_pids, grace_seconds=grace_seconds)
            return status
        except subprocess.TimeoutExpired:
            _signal_process_group(self.process, signal.SIGKILL)
            _signal_process_groups_by_pid(descendant_pids, signal.SIGKILL)
            self.process.wait(timeout=grace_seconds)
            self.status = "failed-forced-cleanup"
            self.exit_code = self.process.returncode
            return self.status

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
        if _matches_preexisting_file(summary_path, self.preexisting_summary):
            return None
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def read_live_events(self) -> LiveEventSnapshot:
        if self.launch is None:
            return LiveEventSnapshot()
        events_path = self.launch.artifact_dir / events.EVENTS_FILENAME
        if not events_path.is_file():
            return LiveEventSnapshot(ready=False)
        if _matches_preexisting_events(events_path, self.preexisting_events):
            return LiveEventSnapshot(ready=False)
        try:
            records, truncated = events.read_events(events_path)
        except (OSError, ValueError) as exc:
            return LiveEventSnapshot(error=str(exc), ready=True)
        return LiveEventSnapshot(events=tuple(records), truncated=truncated, ready=True)


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


def _signal_process_group(process: subprocess.Popen[str], signum: int) -> None:
    pid = getattr(process, "pid", None)
    if pid is None:
        process.send_signal(signum)
        return
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(pid), signum)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.send_signal(signum)


def _descendant_pids(process: subprocess.Popen[str]) -> frozenset[int]:
    pid = getattr(process, "pid", None)
    if pid is None:
        return frozenset()
    children_by_parent = _proc_children_by_parent()
    descendants: set[int] = set()
    pending = list(children_by_parent.get(pid, ()))
    while pending:
        child_pid = pending.pop()
        if child_pid in descendants:
            continue
        descendants.add(child_pid)
        pending.extend(children_by_parent.get(child_pid, ()))
    return frozenset(descendants)


def _proc_children_by_parent() -> dict[int, tuple[int, ...]]:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return {}
    children: dict[int, list[int]] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            stat_text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ppid = _ppid_from_proc_stat(stat_text)
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)
    return {ppid: tuple(pids) for ppid, pids in children.items()}


def _ppid_from_proc_stat(stat_text: str) -> int | None:
    # /proc/<pid>/stat wraps the command name in parentheses; the fields after
    # the final ")" start with state and then parent pid.
    close_paren = stat_text.rfind(")")
    if close_paren == -1:
        return None
    fields = stat_text[close_paren + 1 :].strip().split()
    if len(fields) < 2:
        return None
    try:
        return int(fields[1])
    except ValueError:
        return None


def _terminate_descendants(pids: frozenset[int], *, grace_seconds: float) -> None:
    alive = _alive_pids(pids)
    if not alive:
        return
    _signal_process_groups_by_pid(alive, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while alive and time.monotonic() < deadline:
        time.sleep(0.01)
        alive = _alive_pids(alive)
    if alive:
        _signal_process_groups_by_pid(alive, signal.SIGKILL)


def _alive_pids(pids: frozenset[int]) -> frozenset[int]:
    alive: set[int] = set()
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            alive.add(pid)
        else:
            alive.add(pid)
    return frozenset(alive)


def _signal_process_groups_by_pid(pids: frozenset[int], signum: int) -> None:
    for pid in sorted(pids):
        if pid == os.getpid():
            continue
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            try:
                os.killpg(os.getpgid(pid), signum)
                continue
            except ProcessLookupError:
                continue
            except OSError:
                pass
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            continue
        except OSError:
            continue


def _event_file_identity(path: Path) -> EventFileIdentity | None:
    base_identity = _file_identity(path)
    if base_identity is None:
        return None
    return EventFileIdentity(
        inode=base_identity.inode,
        size=base_identity.size,
        mtime_ns=base_identity.mtime_ns,
        first_run_id=events.first_run_id(path),
    )


def _file_identity(path: Path) -> FileIdentity | None:
    if not path.is_file():
        return None
    stat_result = path.stat()
    inode = stat_result.st_ino if hasattr(stat_result, "st_ino") else None
    return FileIdentity(
        inode=inode,
        size=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
    )


def _matches_preexisting_file(
    path: Path,
    preexisting: FileIdentity | None,
) -> bool:
    if preexisting is None:
        return False
    current = _file_identity(path)
    if current is None:
        return False
    return (
        current.inode == preexisting.inode
        and current.size == preexisting.size
        and current.mtime_ns == preexisting.mtime_ns
    )


def _matches_preexisting_events(
    path: Path,
    preexisting: EventFileIdentity | None,
) -> bool:
    if preexisting is None:
        return False
    current = _event_file_identity(path)
    if current is None:
        return False
    same_identity = (
        current.inode == preexisting.inode
        and current.size == preexisting.size
        and current.mtime_ns == preexisting.mtime_ns
    )
    if same_identity:
        return True
    return (
        current.first_run_id is not None
        and preexisting.first_run_id is not None
        and current.first_run_id == preexisting.first_run_id
    )


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
