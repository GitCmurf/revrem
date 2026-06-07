"""Value tests for the pure engine.decide branch table (REVREM-TASK-003 B3b)."""

from __future__ import annotations

from code_review_loop.core.engine import (
    ChecksDone,
    CommitDone,
    ConfigSnapshot,
    Continue,
    LoopAccumulator,
    NoFinalReview,
    RemediationDone,
    RetryViaChecks,
    RetryViaCommitHook,
    ReviewDone,
    RunChecks,
    RunRemediation,
    RunTriage,
    Stop,
    TriageDone,
    decide,
)
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
)


class _FakeCommitFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(f"commit {kind}")
        self.kind = kind


def test_decide_r3_review_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=False, status="unknown", exc=RuntimeError("boom"))

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeFailed(reason="review_failed", error="boom"))


def test_decide_e1_non_final_clear_without_check_failures_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=False, status="clear")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeClear(reason="review_clear", excerpt=""))


def test_decide_review_non_final_findings_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=False, status="findings")

    action = decide(cfg, acc, event)

    assert action == RunTriage()


def test_decide_review_non_final_clear_with_check_failures_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="pytest failed")
    event = ReviewDone(is_final=False, status="clear")

    action = decide(cfg, acc, event)

    assert action == RunTriage()


def test_decide_f2_final_review_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=True, status="unknown", exc=RuntimeError("boom"))

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeFailed(reason="review_failed", error="boom"))


def test_decide_f3_final_review_pending_check_failures_exits_findings() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="pytest failed")
    event = ReviewDone(is_final=True, status="clear")

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeFindings(
            reason="max_iterations_reached_with_check_failures",
            check_failures=True,
        )
    )


def test_decide_f4_final_review_clear_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=True, status="clear")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeClear(reason="review_clear"))


def test_decide_f5_final_review_findings_exits_findings() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=True, status="findings")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeFindings(reason="max_iterations_reached"))


def test_decide_f6_final_review_unknown_exits_unknown() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = ReviewDone(is_final=True, status="unknown")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeUnknown(reason="max_iterations_reached"))


def test_decide_t6_triage_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = TriageDone(is_clear=False, exc=RuntimeError("triage boom"))

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeFailed(reason="triage_failed", error="triage boom"))


def test_decide_t2_all_findings_suppressed_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = TriageDone(is_clear=True, suppressed_count=2)

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeClear(
            reason="all_findings_suppressed",
            suppressed_findings_count=2,
        )
    )


def test_decide_t3_triage_rejected_all_findings_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = TriageDone(is_clear=True, suppressed_count=0)

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeClear(reason="triage_rejected_all_findings"))


def test_decide_t1_actionable_triage_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = TriageDone(is_clear=False, suppressed_count=0)

    action = decide(cfg, acc, event)

    assert action == RunRemediation()


def test_decide_m3_remediation_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = RemediationDone(exc=RuntimeError("remediation boom"))

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeFailed(reason="remediation_failed", error="remediation boom")
    )


def test_decide_m1_successful_remediation_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = RemediationDone()

    action = decide(cfg, acc, event)

    assert action == RunChecks()


def test_decide_cm7_commit_other_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(status=None, other_exc=RuntimeError("git boom"))

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeFailed(reason="commit_failed", error="git boom"))


def test_decide_cm3_retryable_hook_failure_retries_via_commit_hook() -> None:
    cfg = ConfigSnapshot(3, True, True, "remediate", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("hook_failed"))

    action = decide(cfg, acc, event)

    assert action == RetryViaCommitHook(hook_output="commit hook_failed")


def test_decide_cm4_non_retryable_hook_failure_fails_with_staged_changes() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("hook_failed"))

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeFailed(
            reason="commit_hook_failed",
            error="commit hook_failed",
            staged_changes_left=True,
            check_failures=True,
        )
    )


def test_decide_cm5_non_hook_commit_failure_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(
        status=None, commit_failed=_FakeCommitFailed("nothing_to_commit")
    )

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeFailed(reason="commit_failed", error="commit nothing_to_commit")
    )


def test_decide_cm2_clear_skipped_no_changes_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        pending_check_failures="",
        last_review_status="clear",
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeClear(reason="no_changes_after_remediation"))


def test_decide_cm2_findings_skipped_no_changes_exits_findings() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        pending_check_failures="",
        last_review_status="findings",
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeFindings(reason="no_changes_after_remediation"))


def test_decide_cm2_unknown_skipped_no_changes_exits_unknown() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        pending_check_failures="",
        last_review_status="unknown",
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeUnknown(reason="no_changes_after_remediation"))


def test_decide_cm2_stale_review_resolved_skipped_no_changes_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        pending_check_failures="",
        last_review_status="findings",
        stale_review_resolved=True,
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == Stop(OutcomeClear(reason="stale_review_already_resolved"))


def test_decide_cm1_successful_commit_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(status="committed")

    action = decide(cfg, acc, event)

    assert action == Continue()


def test_decide_cm1_stale_review_resolved_commit_fails_invariant() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="", stale_review_resolved=True)
    event = CommitDone(status="committed")

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeFailed(
            reason="remediation_failed",
            error=(
                "stale review validation emitted resolved marker but produced "
                "changes to commit"
            ),
        )
    )


def test_decide_ck_retry_inner_check_failure_before_next_review() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True, inner_check_retries=1)
    acc = LoopAccumulator(pending_check_failures="ruff failed")

    action = decide(cfg, acc, ChecksDone(), iteration=1)

    assert action == RetryViaChecks()


def test_decide_ck_stale_review_resolved_exits_clear_without_next_review() -> None:
    """Stale-review validation that emits the resolved marker must short-circuit
    the checks phase and return ``stale_review_already_resolved`` before
    ``_next_review_action`` is reached. The previous behaviour fell through to
    the next review action, which produced ``max_iterations_reached`` for
    ``--no-final-review`` runs and triggered a redundant provider call for
    final-review runs.
    """
    cfg = ConfigSnapshot(
        max_iterations=3,
        triage_enabled=True,
        commit_after_remediation=False,
        commit_on_hook_failure="fail",
        final_review=False,
    )
    acc = LoopAccumulator(pending_check_failures="", stale_review_resolved=True)

    action = decide(cfg, acc, ChecksDone(), iteration=1)

    assert action == Stop(OutcomeClear(reason="stale_review_already_resolved"))


def test_decide_ck_stale_review_resolved_takes_precedence_over_pending_check_failures() -> None:
    """When the stale review is resolved but checks still produced failures,
    the resolved state is the authoritative terminal outcome. Pending check
    failures from the just-completed check phase cannot override the
    remediation's own validation that the finding is already resolved.
    """
    cfg = ConfigSnapshot(
        max_iterations=3,
        triage_enabled=True,
        commit_after_remediation=False,
        commit_on_hook_failure="fail",
        final_review=True,
    )
    acc = LoopAccumulator(
        pending_check_failures="untracked non-artifact files remain",
        stale_review_resolved=True,
    )

    action = decide(cfg, acc, ChecksDone(), iteration=2)

    assert action == Stop(OutcomeClear(reason="stale_review_already_resolved"))


def test_decide_ck_stale_review_resolved_exits_before_commit() -> None:
    """Even with auto-commit enabled, a resolved stale review must not reach
    the commit phase. The commit adapter would never see a
    ``CommitDone(status="committed")`` event in this flow because
    ``_decide_checks`` returns the resolved state first.
    """
    cfg = ConfigSnapshot(
        max_iterations=3,
        triage_enabled=True,
        commit_after_remediation=True,
        commit_on_hook_failure="fail",
        final_review=True,
    )
    acc = LoopAccumulator(pending_check_failures="", stale_review_resolved=True)

    action = decide(cfg, acc, ChecksDone(), iteration=1)

    assert action == Stop(OutcomeClear(reason="stale_review_already_resolved"))


def test_decide_ck_inner_check_retry_exhausted_continues_outer_loop() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True, inner_check_retries=1)
    acc = LoopAccumulator(
        pending_check_failures="ruff failed",
        inner_check_retry_count=1,
    )

    action = decide(cfg, acc, ChecksDone(), iteration=1)

    assert action == Continue()


def test_decide_nf1_no_final_review_exits_unknown_with_check_failure_flag() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", False)
    acc = LoopAccumulator(pending_check_failures="pytest failed")
    event = NoFinalReview()

    action = decide(cfg, acc, event)

    assert action == Stop(
        OutcomeUnknown(reason="max_iterations_reached", check_failures=True)
    )


def test_decide_t4_triage_clear_with_pending_check_failures_continues() -> None:
    """Triage cleared review findings but check failures remain — loop must continue (T4)."""
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(pending_check_failures="mypy failed")
    event = TriageDone(is_clear=True, suppressed_count=2)

    action = decide(cfg, acc, event)

    assert action == RunRemediation()


def test_decide_cm3_hook_failure_at_max_iterations_does_not_retry() -> None:
    """Retryable hook failure on the last iteration must not retry (CM4, not CM3)."""
    cfg = ConfigSnapshot(
        max_iterations=3,
        triage_enabled=True,
        commit_after_remediation=True,
        commit_on_hook_failure="remediate",
        final_review=True,
    )
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("hook_failed"))

    action = decide(cfg, acc, event, iteration=3)

    assert action == Stop(
        OutcomeFailed(
            reason="commit_hook_failed",
            error="commit hook_failed",
            staged_changes_left=True,
            check_failures=True,
        )
    )


def test_decide_cm3_no_verify_hook_failure_retries() -> None:
    """commit_on_hook_failure='no-verify' also triggers the retry path (CM3)."""
    cfg = ConfigSnapshot(
        max_iterations=3,
        triage_enabled=True,
        commit_after_remediation=True,
        commit_on_hook_failure="no-verify",
        final_review=True,
    )
    acc = LoopAccumulator(pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("hook_failed"))

    action = decide(cfg, acc, event, iteration=1)

    assert action == RetryViaCommitHook(hook_output="commit hook_failed")
