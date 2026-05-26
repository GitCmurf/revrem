"""Runner/core-engine integration ratchets (REVREM-TASK-003 Wave C)."""

from __future__ import annotations

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
        "git_state_for_resume",
        "git_preflight_stdout",
        "resume_config_payload",
    ):
        assert f"def {helper}(" not in runner_source


def test_runner_stays_below_polish_sprint_size_ceiling() -> None:
    runner_lines = (
        Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py"
    ).read_text(encoding="utf-8").splitlines()

    assert len(runner_lines) < 800
