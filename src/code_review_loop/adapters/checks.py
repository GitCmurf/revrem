"""ChecksAdapter implementation body and verification-check helpers."""

from __future__ import annotations

import os
import re
import shlex
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from code_review_loop.adapters import phase_support
from code_review_loop.core.ports import (
    ChecksOutcome,
    ChecksRequest,
    CommandResult,
    RunContext,
)

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig


# Project-surface markers (moved from cli/__init__.py during C3a step 1).
PYTHON_PROJECT_MARKERS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "requirements.txt",
    "requirements-dev.txt",
)
PYTHON_SCAN_SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "dist",
    "build",
    "node_modules",
    "tmp",
}
NON_PYTHON_PROJECT_MARKERS = (
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "bun.lockb",
    "deno.json",
    "deno.jsonc",
    "tsconfig.json",
)


def adaptive_check_skip_reason(command: Sequence[str], cwd: Path) -> str | None:
    if (
        is_pytest_command(command)
        and has_non_python_project_surface(cwd)
        and not has_python_test_surface(cwd)
    ):
        return "pytest check ignored because this repository appears to be non-Python"
    return None


def normalize_adaptive_check_result(
    command: Sequence[str],
    cwd: Path,
    result: CommandResult,
) -> CommandResult:
    if (
        is_pytest_command(command)
        and result.returncode in {4, 5}
        and has_non_python_project_surface(cwd)
        and not has_python_test_surface(cwd)
    ):
        return CommandResult(
            list(result.args),
            0,
            stdout=(
                "SKIPPED adaptive check: pytest exited "
                f"{result.returncode}, but this repository appears to be non-Python\n"
                + phase_support._combined_output(result)
            ),
        )
    return result


def format_returncode_for_progress(returncode: int) -> str:
    """Render a subprocess return code for operator-facing progress."""
    if returncode >= 0:
        return f"exit {returncode}"
    signal_number = abs(returncode)
    try:
        signal_name = signal.Signals(signal_number).name
    except ValueError:
        return f"exit {returncode} (signal {signal_number})"
    return f"exit {returncode} ({signal_name})"


def format_check_result_for_progress(result: CommandResult) -> str:
    """Render failed check status, preserving timeout evidence when available."""
    combined = phase_support._combined_output(result)
    timeout = re.search(r"Command timed out after ([0-9.]+) seconds", combined)
    if timeout:
        return f"timeout after {timeout.group(1)}s"
    return format_returncode_for_progress(result.returncode)


def all_failed_checks_are_revrem_timeouts(results: Sequence[CommandResult]) -> bool:
    failed = [result for result in results if result.returncode != 0]
    if not failed:
        return False
    return all("Command timed out after " in phase_support._combined_output(result) for result in failed)


def run_worktree_cleanliness_check(config: LoopConfig, runner) -> CommandResult:
    """Fail if remediation left untracked, non-artifact files in the worktree."""
    command = ["git", "status", "--porcelain", "--untracked-files=all"]
    if config.dry_run:
        return CommandResult(command, 0, stdout="DRY_RUN cleanliness check skipped\n")
    if not _has_git_marker(config.cwd):
        return CommandResult(
            command,
            0,
            stdout="SKIPPED cleanliness check: repository has no .git marker\n",
        )
    result = cast(
        CommandResult,
        runner(
            command,
            config.cwd,
            None,
            phase_support.phase_timeout_seconds(config, config.timeout_seconds),
        ),
    )
    if result.returncode != 0:
        combined = phase_support._combined_output(result).lower()
        if "not a git repository" in combined:
            return CommandResult(
                command,
                0,
                stdout="SKIPPED cleanliness check: repository is not a Git worktree\n",
            )
        return result

    untracked = [
        line
        for line in result.stdout.splitlines()
        if line.startswith("?? ") and not _is_artifact_status_line(config, line)
    ]
    if not untracked:
        return CommandResult(command, 0, stdout=result.stdout, stderr=result.stderr)
    return CommandResult(
        command,
        1,
        stdout=(
            "Untracked files remain after remediation:\n"
            + "\n".join(untracked)
            + "\nRemove scratch files, or intentionally add legitimate new files before checks pass.\n"
        ),
        stderr=result.stderr,
    )


def _is_artifact_status_line(config: LoopConfig, line: str) -> bool:
    path_text = line[3:].strip()
    if not path_text:
        return False
    artifact_dir = config.artifact_dir
    try:
        artifact_rel = artifact_dir.resolve().relative_to(config.cwd.resolve())
    except ValueError:
        return False
    artifact_prefix = artifact_rel.as_posix().rstrip("/") + "/"
    return path_text == artifact_rel.as_posix() or path_text.startswith(artifact_prefix)


def _has_git_marker(cwd: Path) -> bool:
    root = cwd.resolve()
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return candidate not in {Path("/tmp"), Path("/var/tmp")} or candidate == root
    return False


def is_pytest_command(command: Sequence[str]) -> bool:
    if not command:
        return False
    first = Path(command[0]).name
    if first in {"pytest", "py.test"}:
        return True
    if first.startswith("pytest"):
        return True
    return len(command) >= 3 and first.startswith("python") and command[1:3] == ("-m", "pytest")


def has_non_python_project_surface(cwd: Path) -> bool:
    root = cwd.resolve()
    return any((root / marker).exists() for marker in NON_PYTHON_PROJECT_MARKERS)


def has_python_test_surface(cwd: Path) -> bool:
    root = cwd.resolve()
    if any((root / marker).exists() for marker in PYTHON_PROJECT_MARKERS):
        return True
    tests_dir = root / "tests"
    return tests_dir.is_dir() and any(
        path.suffix == ".py" for path in iter_project_files(tests_dir)
    )


def iter_project_files(root: Path):
    if not root.exists():
        return
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in PYTHON_SCAN_SKIP_DIRS and not name.startswith(".")
        ]
        current_path = Path(current)
        for filename in filenames:
            yield current_path / filename


def run_checks(
    config: LoopConfig,
    runner,
    iteration: int,
    ctx: RunContext,
    *,
    artifact_label: str | None = None,
    display_label: str | None = None,
) -> tuple[list[CommandResult], list[str]]:
    """Execute the configured check commands for ``iteration`` and return
    ``(results, failed_commands)``. Loop-shell side effects (progress events,
    artifact writes) are routed through ``adapters.phase_support``.
    """
    artifact_prefix = artifact_label or str(iteration)
    display_prefix = display_label or str(iteration)
    results: list[CommandResult] = []

    cleanliness_check = "git status --porcelain --untracked-files=all"
    phase_support.progress_event(
        config, "check", f"{display_prefix}.1", "start", cleanliness_check, ctx=ctx
    )
    cleanliness_result = run_worktree_cleanliness_check(config, runner)
    results.append(cleanliness_result)
    phase_support.write_artifact(
        config.artifact_dir / f"check-{artifact_prefix}-1.txt",
        phase_support._combined_output(cleanliness_result),
    )
    if ctx.event_sink is not None:
        ctx.event_sink.emit(
            "check_result",
            phase="check",
            iteration=f"{display_prefix}.1",
            payload={
                "command": cleanliness_check,
                "returncode": cleanliness_result.returncode,
                "status": "passed" if cleanliness_result.returncode == 0 else "failed",
                "artifact": f"check-{artifact_prefix}-1.txt",
            },
        )
    if cleanliness_result.returncode == 0:
        phase_support.progress_event(config, "check", f"{display_prefix}.1", "passed", ctx=ctx)
    else:
        phase_support.progress_event(
            config,
            "check",
            f"{display_prefix}.1",
            "failed",
            format_check_result_for_progress(cleanliness_result),
            ctx=ctx,
        )

    for index, check in enumerate(config.check_commands, start=2):
        command = shlex.split(check)
        phase_support.progress_event(config, "check", f"{display_prefix}.{index}", "start", check, ctx=ctx)
        adaptive_skip = adaptive_check_skip_reason(command, config.cwd)
        if adaptive_skip:
            result = CommandResult(
                command,
                0,
                stdout=f"SKIPPED adaptive check: {adaptive_skip}\n",
            )
        elif config.dry_run:
            result = CommandResult(command, 0, stdout=f"DRY_RUN check skipped: {check}\n")
        else:
            # Checks intentionally follow the global loop timeout, not the
            # remediation-specific timeout, so remediation tuning does not make
            # verification commands spuriously fail or run forever.
            result = runner(
                command, config.cwd, None, phase_support.phase_timeout_seconds(config, config.timeout_seconds)
            )
            result = normalize_adaptive_check_result(command, config.cwd, result)
        results.append(result)
        phase_support.write_artifact(
            config.artifact_dir / f"check-{artifact_prefix}-{index}.txt",
            phase_support._combined_output(result),
        )
        if ctx.event_sink is not None:
            ctx.event_sink.emit(
                "check_result",
                phase="check",
                iteration=f"{display_prefix}.{index}",
                payload={
                    "command": check,
                    "returncode": result.returncode,
                    "status": "passed" if result.returncode == 0 else "failed",
                    "artifact": f"check-{artifact_prefix}-{index}.txt",
                },
            )
        if result.returncode == 0 and result.stdout.startswith("SKIPPED adaptive check:"):
            phase_support.progress_event(
                config, "check", f"{display_prefix}.{index}", "skipped", result.stdout.strip(), ctx=ctx
            )
        elif result.returncode == 0:
            phase_support.progress_event(config, "check", f"{display_prefix}.{index}", "passed", ctx=ctx)
        else:
            phase_support.progress_event(
                config,
                "check",
                f"{display_prefix}.{index}",
                "failed",
                format_check_result_for_progress(result),
                ctx=ctx,
            )
    command_names = (cleanliness_check, *config.check_commands)
    failed_commands = [
        command_names[i] for i, r in enumerate(results) if r.returncode != 0
    ]
    return results, failed_commands


def format_check_failures(check_results: list[CommandResult]) -> str:
    """Render a human-readable summary of failed checks for remediation prompts."""
    failures = [r for r in check_results if r.returncode != 0]
    if not failures:
        return ""
    parts = ["Check failures from the previous iteration:"]
    for r in failures:
        parts.append(f"\n$ {shlex.join(r.args)}\n{phase_support._combined_output(r)}")
    return "\n".join(parts)


class ChecksAdapter:
    """Implements ChecksHarness via the in-module ``run_checks`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
        results, failed = run_checks(
            self._config,
            ctx.runner,
            request.iteration,
            ctx=ctx,
            artifact_label=request.artifact_label,
            display_label=request.display_label,
        )
        return ChecksOutcome(
            results=tuple(results),
            failed_commands=tuple(failed),
        )
