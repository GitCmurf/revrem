from __future__ import annotations

from pathlib import Path

from code_review_loop import application
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult


def test_run_review_loop_is_non_cli_application_entrypoint(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def process_runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")
        raise AssertionError(f"unexpected command: {args}")

    summary = application.run_review_loop(
        LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            progress=False,
        ),
        process_runner,
    )

    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "review_clear"
    assert [call[1] for call in calls] == ["review"]
