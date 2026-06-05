"""Runner/core-engine integration ratchets (REVREM-TASK-003 Wave C)."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def test_runner_uses_core_engine_run_without_direct_decide_bridge() -> None:
    runner_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py").read_text(
        encoding="utf-8"
    )
    shell_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner_shell.py").read_text(
        encoding="utf-8"
    )

    assert "run as run_engine" in shell_source
    assert "decide as decide_engine" not in runner_source
    assert "decide as decide_engine" not in shell_source
    assert "max_steps=1" not in runner_source
    assert "max_steps=1" not in shell_source
    assert "_CaptureEngineAction" not in runner_source
    assert "_CaptureEngineAction" not in shell_source
    assert not re.search(r"\bdecide\s*\(", runner_source)
    assert not re.search(r"\bdecide\s*\(", shell_source)


def test_engine_acceptance_imports_only_core_modules() -> None:
    path = Path(__file__).resolve().parents[1] / "tests" / "test_engine_run.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("code_review_loop.") and not alias.name.startswith("code_review_loop.core."):
                    offenders.append(f"{path.name}:{node.lineno}: import {alias.name}")
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("code_review_loop.")
            and not node.module.startswith("code_review_loop.core.")
        ):
            offenders.append(f"{path.name}:{node.lineno}: from {node.module} import ...")

    assert offenders == []


def test_runner_shell_has_no_reverse_runner_import() -> None:
    shell_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner_shell.py").read_text(
        encoding="utf-8"
    )
    runner_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py").read_text(
        encoding="utf-8"
    )

    assert "from code_review_loop import runner" not in shell_source
    assert "import code_review_loop.runner" not in shell_source
    assert "class _RunnerEngineExecutor" not in runner_source


def test_runner_no_longer_owns_terminal_control() -> None:
    runner_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py").read_text(
        encoding="utf-8"
    )

    assert 'Path("/dev/tty")' not in runner_source
    assert "TERMINAL_TITLE_SAVE" not in runner_source
    assert "TERMINAL_TITLE_RESTORE" not in runner_source
    assert "CURSOR_SHOW" not in runner_source


def test_runner_no_longer_owns_process_or_resume_support() -> None:
    runner_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py").read_text(
        encoding="utf-8"
    )

    for helper in (
        "default_runner",
        "run_subprocess_with_terminal_title_refresh",
        "kill_process_tree",
        "subprocess_runner",
        "git_state_for_resume",
        "git_preflight_stdout",
        "resume_config_payload",
    ):
        assert f"def {helper}(" not in runner_source
        assert helper not in runner_source


def test_tests_do_not_import_private_runner() -> None:
    root = Path(__file__).resolve().parents[1] / "tests"
    leaks: list[str] = []
    for path in root.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "code_review_loop.runner":
                        leaks.append(f"{path.name}:{node.lineno}: import code_review_loop.runner")
            if isinstance(node, ast.ImportFrom) and node.module in {
                "code_review_loop",
                "code_review_loop.runner",
            }:
                for alias in node.names:
                    if node.module == "code_review_loop.runner" or alias.name == "runner":
                        leaks.append(f"{path.name}:{node.lineno}: from {node.module} import {alias.name}")

    assert leaks == []


def test_runner_stays_below_polish_sprint_size_ceiling() -> None:
    runner_lines = (
        Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py"
    ).read_text(encoding="utf-8").splitlines()

    assert len(runner_lines) < 300


def test_runner_shell_stays_orchestration_sized() -> None:
    shell_lines = (
        Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner_shell.py"
    ).read_text(encoding="utf-8").splitlines()

    assert len(shell_lines) < 500
