"""Tests for RunState semantic terminal transitions."""

from __future__ import annotations

from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
)
from code_review_loop.core.state import RunState


def _state() -> RunState:
    return RunState.create(
        base="main",
        git_state={},
        resume_config={},
        run_id="run-1",
        started_at="2026-05-25T00:00:00Z",
        profile=None,
        max_iterations=1,
        artifact_dir="artifacts",
        commit_on_hook_failure="fail",
        budgets={},
        initial_review_file=None,
    )


def test_mark_outcome_clear_records_reason_and_suppression_count() -> None:
    state = _state()

    state.mark_outcome(OutcomeClear(reason="all_findings_suppressed", suppressed_findings_count=2))

    summary = state.to_dict()
    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "all_findings_suppressed"
    assert summary["suppressed_findings_count"] == 2


def test_mark_outcome_failed_records_error_and_flags() -> None:
    state = _state()

    state.mark_outcome(
        OutcomeFailed(
            reason="commit_hook_failed",
            error="hook failed",
            staged_changes_left=True,
            check_failures=True,
        )
    )

    summary = state.to_dict()
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "commit_hook_failed"
    assert summary["error"] == "hook failed"
    assert summary["staged_changes_left"] is True
    assert summary["pending_check_failures"] is True


def test_mark_outcome_findings_and_unknown_preserve_terminal_status() -> None:
    findings = _state()
    findings.mark_outcome(OutcomeFindings(reason="max_iterations_reached", check_failures=True))
    assert findings.to_dict()["final_status"] == "findings"
    assert findings.to_dict()["pending_check_failures"] is True

    unknown = _state()
    unknown.mark_outcome(OutcomeUnknown(reason="max_iterations_reached"))
    assert unknown.to_dict()["final_status"] == "unknown"
    assert unknown.to_dict()["stopped_reason"] == "max_iterations_reached"
