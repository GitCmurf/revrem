"""ChecksAdapter implementation body and verification-check helpers."""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from code_review_loop.adapters import phase_support as _cli
from code_review_loop.core.ports import CommandResult, RunContext

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
        and result.returncode in {2, 4, 5}
        and has_non_python_project_surface(cwd)
        and not has_python_test_surface(cwd)
    ):
        return CommandResult(
            list(result.args),
            0,
            stdout=(
                "SKIPPED adaptive check: pytest exited "
                f"{result.returncode}, but this repository appears to be non-Python\n"
                + _cli._combined_output(result)
            ),
        )
    return result


def is_pytest_command(command: Sequence[str]) -> bool:
    if not command:
        return False
    first = Path(command[0]).name
    if first in {"pytest", "py.test"}:
        return True
    if first.startswith("pytest"):
        return True
    return len(command) >= 3 and first.startswith("python") and command[1:3] == ["-m", "pytest"]


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
) -> tuple[list[CommandResult], list[str]]:
    """Execute the configured check commands for ``iteration`` and return
    ``(results, failed_commands)``. Loop-shell side effects (progress events,
    artifact writes) are routed through ``adapters.phase_support``.
    """
    results: list[CommandResult] = []
    for index, check in enumerate(config.check_commands, start=1):
        command = shlex.split(check)
        _cli.progress_event(config, "check", f"{iteration}.{index}", "start", check, ctx=ctx)
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
                command, config.cwd, None, _cli.phase_timeout_seconds(config, config.timeout_seconds)
            )
            result = normalize_adaptive_check_result(command, config.cwd, result)
        results.append(result)
        _cli.write_artifact(
            config.artifact_dir / f"check-{iteration}-{index}.txt",
            _cli._combined_output(result),
        )
        if ctx.event_sink is not None:
            ctx.event_sink.emit(
                "check_result",
                phase="check",
                iteration=f"{iteration}.{index}",
                payload={
                    "command": check,
                    "returncode": result.returncode,
                    "status": "passed" if result.returncode == 0 else "failed",
                    "artifact": f"check-{iteration}-{index}.txt",
                },
            )
        if result.returncode == 0 and result.stdout.startswith("SKIPPED adaptive check:"):
            _cli.progress_event(
                config, "check", f"{iteration}.{index}", "skipped", result.stdout.strip(), ctx=ctx
            )
        elif result.returncode == 0:
            _cli.progress_event(config, "check", f"{iteration}.{index}", "passed", ctx=ctx)
        else:
            _cli.progress_event(
                config, "check", f"{iteration}.{index}", "failed", f"exit {result.returncode}", ctx=ctx
            )
    failed_commands = [config.check_commands[i] for i, r in enumerate(results) if r.returncode != 0]
    return results, failed_commands


def format_check_failures(check_results: list[CommandResult]) -> str:
    """Render a human-readable summary of failed checks for remediation prompts."""
    failures = [r for r in check_results if r.returncode != 0]
    if not failures:
        return ""
    parts = ["Check failures from the previous iteration:"]
    for r in failures:
        parts.append(f"\n$ {shlex.join(r.args)}\n{_cli._combined_output(r)}")
    return "\n".join(parts)
