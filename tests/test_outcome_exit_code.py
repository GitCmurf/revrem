"""Per-code reachability tests for outcome_to_exit_code (REVREM-TASK-003 B3c-ii)."""

from __future__ import annotations

import pytest

from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    outcome_to_exit_code,
)


def test_clear_exits_0() -> None:
    assert outcome_to_exit_code(OutcomeClear(reason="review_clear")) == 0


def test_resolved_stale_review_exits_0() -> None:
    assert outcome_to_exit_code(OutcomeClear(reason="stale_review_already_resolved")) == 0


def test_clear_with_suppressed_findings_exits_0() -> None:
    assert outcome_to_exit_code(OutcomeClear(reason="all_findings_suppressed", suppressed_findings_count=3)) == 0


def test_failed_default_exits_1() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="review_failed", error="boom")) == 1


def test_failed_triage_exits_1() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="triage_failed", error="x")) == 1


def test_failed_remediation_exits_1() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="remediation_failed", error="x")) == 1


def test_failed_commit_exits_1() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="commit_failed", error="x")) == 1


def test_failed_commit_hook_exits_1() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="commit_hook_failed", error="x")) == 1


def test_failed_engine_step_limit_exits_1() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="engine_step_limit_exceeded", error="x")) == 1


def test_failed_budget_ceiling_exits_3() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="budget_ceiling_hit", error="over budget")) == 3


def test_failed_setup_exits_4() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="setup_failed", error="bad config")) == 4


def test_failed_cancelled_exits_5() -> None:
    assert outcome_to_exit_code(OutcomeFailed(reason="cancelled", error="operator signal")) == 5


def test_findings_exits_2() -> None:
    assert outcome_to_exit_code(OutcomeFindings(reason="max_iterations_reached")) == 2


def test_findings_with_check_failures_exits_2() -> None:
    assert outcome_to_exit_code(OutcomeFindings(reason="max_iterations_reached_with_check_failures", check_failures=True)) == 2


def test_unknown_exits_2() -> None:
    assert outcome_to_exit_code(OutcomeUnknown(reason="max_iterations_reached")) == 2


def test_unknown_with_check_failures_exits_2() -> None:
    assert outcome_to_exit_code(OutcomeUnknown(reason="max_iterations_reached", check_failures=True)) == 2


@pytest.mark.parametrize("code,outcome", [
    (0, OutcomeClear(reason="review_clear")),
    (1, OutcomeFailed(reason="review_failed", error="x")),
    (1, OutcomeFailed(reason="triage_failed", error="x")),
    (1, OutcomeFailed(reason="remediation_failed", error="x")),
    (1, OutcomeFailed(reason="commit_failed", error="x")),
    (1, OutcomeFailed(reason="commit_hook_failed", error="x")),
    (1, OutcomeFailed(reason="engine_step_limit_exceeded", error="x")),
    (2, OutcomeFindings(reason="max_iterations_reached")),
    (2, OutcomeUnknown(reason="max_iterations_reached")),
    (3, OutcomeFailed(reason="budget_ceiling_hit", error="x")),
    (4, OutcomeFailed(reason="setup_failed", error="x")),
    (5, OutcomeFailed(reason="cancelled", error="x")),
])
def test_parametrized_all_codes_reachable(code: int, outcome: OutcomeClear | OutcomeFailed | OutcomeFindings | OutcomeUnknown) -> None:
    assert outcome_to_exit_code(outcome) == code
