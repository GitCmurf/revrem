from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import application
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import OutcomeClear
from code_review_loop.core.ports import CommandResult


def test_run_review_loop_is_non_cli_application_entrypoint(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def process_runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")
        raise AssertionError(f"unexpected command: {args}")

    result = application.run_review_loop(
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

    assert result.final_status == "clear"
    assert result.stopped_reason == "review_clear"
    assert result.to_dict()["final_status"] == "clear"
    assert [call[1] for call in calls] == ["review"]


def test_application_api_does_not_export_runner_alias() -> None:
    assert "Runner" not in application.__all__
    assert not hasattr(application, "Runner")


def test_review_loop_result_to_dict_deep_copies_nested_summary() -> None:
    result = application.ReviewLoopResult(
        summary={
            "final_status": "clear",
            "iterations": [{"iteration": 1, "review_status": "clear"}],
            "artifact_paths": {"reviews": ["review-1.txt"]},
        },
        outcome=OutcomeClear(reason="review_clear"),
    )

    projected = result.to_dict()
    iterations = projected["iterations"]
    artifact_paths = projected["artifact_paths"]
    assert isinstance(iterations, list)
    assert isinstance(artifact_paths, dict)
    iterations.append({"iteration": 2, "review_status": "findings"})
    artifact_paths["reviews"].append("review-2.txt")  # type: ignore[index, union-attr]

    fresh = result.to_dict()
    assert fresh["iterations"] == [{"iteration": 1, "review_status": "clear"}]
    assert fresh["artifact_paths"] == {"reviews": ["review-1.txt"]}


def test_resume_review_loop_reports_missing_summary(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="summary.json not found in run directory"):
        application.resume_review_loop(tmp_path / "missing-run")
