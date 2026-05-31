from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import application, budgets
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
)
from tests.support.headless import (
    HeadlessRun,
    RecordingRemediationHarness,
    SequencedChecksHarness,
    SequencedReviewHarness,
)


def test_headless_application_clear_review(tmp_path: Path) -> None:
    run = HeadlessRun.with_tmp_config(tmp_path, review=SequencedReviewHarness(["clear"]))

    result = run.run()

    assert result.final_status == "clear"
    assert isinstance(result.outcome, OutcomeClear)
    assert result.stopped_reason == "review_clear"
    assert run.review.calls[0].artifact_label == "review-1"


def test_headless_application_terminal_ui_false_suppresses_progress_output(
    tmp_path: Path,
    capsys,
) -> None:
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=True,
        triage_enabled=False,
    )
    run = HeadlessRun(
        config=config,
        review=SequencedReviewHarness(["clear"]),
    )

    result = run.run()

    captured = capsys.readouterr()
    assert result.final_status == "clear"
    assert captured.err == ""


def test_headless_application_findings_remediation_checks_final_clear(tmp_path: Path) -> None:
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        triage_enabled=True,
    )
    run = HeadlessRun(
        config=config,
        review=SequencedReviewHarness(["findings", "clear"]),
        checks=SequencedChecksHarness([()]),
    )

    result = run.run()

    assert result.final_status == "clear"
    assert isinstance(result.outcome, OutcomeClear)
    assert [request.iteration for request in run.remediation.calls] == [1]
    assert [request.iteration for request in run.checks.calls] == [1]
    assert [request.display_label for request in run.review.calls] == ["1", "final"]


def test_headless_application_check_failure_feeds_next_iteration(tmp_path: Path) -> None:
    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        triage_enabled=False,
    )
    run = HeadlessRun(
        config=config,
        review=SequencedReviewHarness(["findings", "findings", "clear"]),
        checks=SequencedChecksHarness([("pytest tests/",), ()]),
    )

    result = run.run()

    assert result.final_status == "clear"
    assert isinstance(result.outcome, OutcomeClear)
    assert [request.iteration for request in run.remediation.calls] == [1, 2]
    assert "pytest tests/ failed" in run.remediation.calls[1].remediation_input


def test_headless_application_findings_outcome_is_typed(tmp_path: Path) -> None:
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        triage_enabled=False,
    )
    run = HeadlessRun(config=config, review=SequencedReviewHarness(["findings", "findings"]))

    result = run.run()

    assert result.final_status == "findings"
    assert isinstance(result.outcome, OutcomeFindings)


def test_headless_application_unknown_outcome_is_typed(tmp_path: Path) -> None:
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        triage_enabled=False,
        final_review=False,
    )
    run = HeadlessRun(config=config, review=SequencedReviewHarness(["findings"]))

    result = run.run()

    assert result.final_status == "unknown"
    assert isinstance(result.outcome, OutcomeUnknown)


def test_headless_application_setup_failure_summary(tmp_path: Path) -> None:
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        preflight_enabled=True,
        review_harness="definitely-missing",
    )

    with pytest.raises(application.RunLoopFailed) as excinfo:
        application.run_review_loop(config, terminal_ui=False)

    assert excinfo.value.summary["final_status"] == "error"
    assert excinfo.value.summary["stopped_reason"] == "setup_failed"
    assert isinstance(excinfo.value.outcome, OutcomeFailed)


def test_headless_application_budget_failure_summary(tmp_path: Path) -> None:
    exc = budgets.BudgetExceeded(ceiling="tokens", limit=1, actual=2)
    run = HeadlessRun.with_tmp_config(
        tmp_path,
        review=SequencedReviewHarness(["findings"]),
        remediation=RecordingRemediationHarness(exc),
    )

    with pytest.raises(application.RunLoopFailed) as excinfo:
        run.run()

    assert excinfo.value.summary["final_status"] == "error"
    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"
    assert isinstance(excinfo.value.outcome, OutcomeFailed)


def test_headless_application_cancellation_summary(tmp_path: Path) -> None:
    run = HeadlessRun.with_tmp_config(
        tmp_path,
        review=SequencedReviewHarness(["findings"]),
        remediation=RecordingRemediationHarness(KeyboardInterrupt()),
    )

    with pytest.raises(application.RunLoopFailed) as excinfo:
        run.run()

    assert excinfo.value.summary["final_status"] == "error"
    assert excinfo.value.summary["stopped_reason"] == "cancelled"
    assert isinstance(excinfo.value.outcome, OutcomeFailed)


def test_headless_application_resume_uses_injected_runner(tmp_path: Path) -> None:
    from code_review_loop.core.ports import CommandResult

    def process_runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
    )
    initial_result = application.run_review_loop(config, process_runner, terminal_ui=False)
    assert initial_result.final_status == "clear"

    resumed = HeadlessRun.with_tmp_config(tmp_path, review=SequencedReviewHarness(["clear"]))
    result = application.resume_review_loop(
        tmp_path / "artifacts",
        cwd=tmp_path,
        process_runner=resumed.process_runner,
        clock=resumed.clock,
        identity=resumed.identity,
        phase_harnesses=resumed.phase_harnesses(),
        terminal_ui=False,
    )

    assert result.final_status == "clear"
    assert isinstance(result.outcome, OutcomeClear)
