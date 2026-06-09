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
from code_review_loop.git_status import (
    is_artifact_path,
    untracked_paths_from_status_z,
)
from code_review_loop.repo_roots import lexical_git_repo_root

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
    timeout = re.search(r"Command timed out after ([0-9.]+) second(?:s)?", combined)
    if timeout:
        return f"timeout after {timeout.group(1)}s"
    return format_returncode_for_progress(result.returncode)


def all_failed_checks_are_revrem_timeouts(results: Sequence[CommandResult]) -> bool:
    failed = [result for result in results if result.returncode != 0]
    if not failed:
        return False
    return all(
        "Command timed out after " in phase_support._combined_output(result) for result in failed
    )


def run_worktree_cleanliness_check(
    config: LoopConfig,
    runner,
) -> CommandResult:
    """Fail if remediation left untracked, non-artifact files in the worktree.

    RevRem refuses to enable auto-commit from a dirty worktree before the loop
    starts, so untracked non-artifact files that appear after remediation are
    treated as intentional remediation output. They are marked with
    ``git add --intent-to-add`` so the upcoming ``git add -A`` in the commit
    phase can pick them up. Known generated output should be covered by
    ``.gitignore`` or the artifact-dir exemption; secret and policy violations
    should be caught by configured verification or commit hooks.

    The status call uses ``git status -z`` so untracked paths are returned
    verbatim. The line-oriented ``--porcelain`` output wraps any path that
    contains an "unusual" character (spaces, backslashes, non-ASCII bytes,
    etc.) in C-style quotes and escapes, and forwarding that quoted form to
    ``git add --intent-to-add`` makes the pathspec miss the file. NUL-delimited
    output does not quote or escape, so the parsed paths are passed through
    unchanged.
    """
    command = ["git", "status", "-z", "--porcelain=v1", "--untracked-files=all"]
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

    untracked = _untracked_non_artifact_paths(config, result.stdout)
    if not untracked:
        return CommandResult(command, 0, stdout=result.stdout, stderr=result.stderr)
    if not config.commit_after_remediation:
        return _cleanliness_check_untracked_no_commit(command, untracked, result.stderr)
    intent_added, intent_errors = _intent_add_untracked(config, runner, untracked)
    if intent_errors:
        return CommandResult(
            command,
            1,
            stdout=(
                "Untracked files remain after remediation and could not be intent-added:\n"
                + "\n".join(intent_errors)
                + "\nRemove scratch files, or fix the underlying git error before checks pass.\n"
            ),
            stderr=result.stderr,
        )
    recheck = cast(
        CommandResult,
        runner(
            command,
            config.cwd,
            None,
            phase_support.phase_timeout_seconds(config, config.timeout_seconds),
        ),
    )
    if recheck.returncode != 0:
        return recheck
    remaining = _untracked_non_artifact_paths(config, recheck.stdout)
    if remaining:
        return CommandResult(
            command,
            1,
            stdout=(
                "Untracked files remain after remediation:\n"
                + "\n".join(remaining)
                + "\nRemove scratch files, or intentionally add legitimate new files before checks pass.\n"
            ),
            stderr=recheck.stderr,
        )
    if intent_added:
        summary = (
            "Worktree cleanliness check passed; auto-staged untracked files with "
            "--intent-to-add:\n" + "\n".join(f"  + {path}" for path in intent_added)
        )
    else:
        summary = "Worktree cleanliness check passed."
    return CommandResult(command, 0, stdout=summary + "\n", stderr=recheck.stderr)


def _untracked_non_artifact_paths(config: LoopConfig, status_stdout: str) -> list[str]:
    """Return the decoded untracked non-artifact paths from ``git status -z``."""
    return [
        path
        for path in untracked_paths_from_status_z(status_stdout)
        if not is_artifact_path(config, path)
    ]


def _cleanliness_check_untracked_no_commit(
    command: list[str],
    untracked: list[str],
    stderr: str,
) -> CommandResult:
    """Fail the cleanliness check when untracked non-artifact files remain.

    Check-only remediation runs must not mutate the operator's git index, so
    ``git add --intent-to-add`` is skipped entirely. The untracked paths are
    surfaced in a non-zero exit result so the operator and the model must
    account for them before the loop can report clear: legitimate new files
    must be added explicitly, scratch files must be deleted, or the run must
    be re-launched with ``--commit`` to let RevRem stage them. Returning exit
    code 0 here would let untracked files escape the post-remediation check
    while subsequent ``git diff``-based review context silently omits them.
    """
    listed = "\n".join(f"  + {path}" for path in untracked)
    summary = (
        "Worktree cleanliness check FAILED: auto-commit is disabled so RevRem "
        "will not stage untracked non-artifact files, and downstream review "
        "context is built from ``git diff`` so these paths would be omitted "
        "from the reviewed patch. Remove scratch files, explicitly stage "
        "legitimate new files, or re-run with ``--commit`` to let RevRem "
        "stage them. The following untracked paths must be accounted for:\n" + listed + "\n"
    )
    return CommandResult(command, 1, stdout=summary, stderr=stderr)


def _intent_add_untracked(
    config: LoopConfig, runner, untracked_paths: list[str]
) -> tuple[list[str], list[str]]:
    """Run ``git add --intent-to-add`` for each untracked non-artifact path.

    Returns ``(intent_added_paths, error_lines)``. ``git add -N`` registers the
    file with the index without writing its content, so the upcoming
    ``git add -A`` in the commit phase can pick it up without the model having
    to stage files itself.

    ``git status -z`` always emits paths relative to the repository root, even
    when RevRem is launched from a subdirectory. The intent-add subprocess
    must therefore be rooted at the git worktree so the pathspec matches the
    index's view of the tree; otherwise Git resolves the path against
    ``config.cwd`` and the pathspec misses the file.

    The paths fed in here are already decoded (no surrounding quotes, no
    C-style escapes), so they can be forwarded to ``git add`` byte-for-byte.
    """
    intent_added: list[str] = []
    intent_errors: list[str] = []
    timeout_seconds = phase_support.phase_timeout_seconds(config, config.timeout_seconds)
    intent_cwd = lexical_git_repo_root(config.cwd) or config.cwd
    for path_text in untracked_paths:
        if not path_text:
            continue
        add_result = runner(
            ["git", "add", "--intent-to-add", "--", path_text],
            intent_cwd,
            None,
            timeout_seconds,
        )
        if add_result.returncode == 0:
            intent_added.append(path_text)
        else:
            detail = phase_support._combined_output(add_result).strip() or "git add failed"
            intent_errors.append(f"{path_text}: {detail}")
    return intent_added, intent_errors


def _has_git_marker(cwd: Path) -> bool:
    return lexical_git_repo_root(cwd) is not None


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

    cleanliness_check = "git status -z --porcelain=v1 --untracked-files=all"
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
        phase_support.progress_event(
            config, "check", f"{display_prefix}.{index}", "start", check, ctx=ctx
        )
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
                command,
                config.cwd,
                None,
                phase_support.phase_timeout_seconds(config, config.timeout_seconds),
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
                config,
                "check",
                f"{display_prefix}.{index}",
                "skipped",
                result.stdout.strip(),
                ctx=ctx,
            )
        elif result.returncode == 0:
            phase_support.progress_event(
                config, "check", f"{display_prefix}.{index}", "passed", ctx=ctx
            )
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
    failed_commands = [command_names[i] for i, r in enumerate(results) if r.returncode != 0]
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
