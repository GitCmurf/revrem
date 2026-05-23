"""Value tests for the pure engine.decide branch table (REVREM-TASK-003 B3b)."""

from __future__ import annotations

from code_review_loop.core.engine import (
    CommitDone,
    ConfigSnapshot,
    Continue,
    ExitClear,
    ExitFailed,
    ExitFindings,
    ExitUnknown,
    LoopAccumulator,
    NoFinalReview,
    RemediationDone,
    RetryViaCommitHook,
    ReviewDone,
    TriageDone,
    decide,
)


class _FakeCommitFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(f"commit {kind}")
        self.kind = kind


def test_decide_r3_review_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = ReviewDone(is_final=False, status="unknown", exc=RuntimeError("boom"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(reason="review_failed", error="boom")


def test_decide_e1_non_final_clear_without_check_failures_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = ReviewDone(is_final=False, status="clear")

    action = decide(cfg, acc, event)

    assert action == ExitClear(reason="review_clear", excerpt="")


def test_decide_review_non_final_findings_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = ReviewDone(is_final=False, status="findings")

    action = decide(cfg, acc, event)

    assert action == Continue()


def test_decide_review_non_final_clear_with_check_failures_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="pytest failed")
    event = ReviewDone(is_final=False, status="clear")

    action = decide(cfg, acc, event)

    assert action == Continue()


def test_decide_f2_final_review_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=3, pending_check_failures="")
    event = ReviewDone(is_final=True, status="unknown", exc=RuntimeError("boom"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(reason="review_failed", error="boom")


def test_decide_f3_final_review_pending_check_failures_exits_findings() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=3, pending_check_failures="pytest failed")
    event = ReviewDone(is_final=True, status="clear")

    action = decide(cfg, acc, event)

    assert action == ExitFindings(
        reason="max_iterations_reached_with_check_failures",
        check_failures=True,
    )


def test_decide_f4_final_review_clear_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=3, pending_check_failures="")
    event = ReviewDone(is_final=True, status="clear")

    action = decide(cfg, acc, event)

    assert action == ExitClear(reason="review_clear")


def test_decide_f5_final_review_findings_exits_findings() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=3, pending_check_failures="")
    event = ReviewDone(is_final=True, status="findings")

    action = decide(cfg, acc, event)

    assert action == ExitFindings(reason="max_iterations_reached")


def test_decide_f6_final_review_unknown_exits_unknown() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=3, pending_check_failures="")
    event = ReviewDone(is_final=True, status="unknown")

    action = decide(cfg, acc, event)

    assert action == ExitUnknown(reason="max_iterations_reached")


def test_decide_t6_triage_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = TriageDone(is_clear=False, exc=RuntimeError("triage boom"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(reason="triage_failed", error="triage boom")


def test_decide_t2_all_findings_suppressed_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = TriageDone(is_clear=True, suppressed_count=2)

    action = decide(cfg, acc, event)

    assert action == ExitClear(
        reason="all_findings_suppressed",
        suppressed_findings_count=2,
    )


def test_decide_t3_triage_rejected_all_findings_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = TriageDone(is_clear=True, suppressed_count=0)

    action = decide(cfg, acc, event)

    assert action == ExitClear(reason="triage_rejected_all_findings")


def test_decide_t1_actionable_triage_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = TriageDone(is_clear=False, suppressed_count=0)

    action = decide(cfg, acc, event)

    assert action == Continue()


def test_decide_m3_remediation_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = RemediationDone(exc=RuntimeError("remediation boom"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(reason="remediation_failed", error="remediation boom")


def test_decide_m1_successful_remediation_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = RemediationDone()

    action = decide(cfg, acc, event)

    assert action == Continue()


def test_decide_cm7_commit_other_exception_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = CommitDone(status=None, other_exc=RuntimeError("git boom"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(reason="commit_failed", error="git boom")


def test_decide_cm3_retryable_hook_failure_retries_via_commit_hook() -> None:
    cfg = ConfigSnapshot(3, True, True, "remediate", True)
    acc = LoopAccumulator(iteration=2, pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("hook_failed"))

    action = decide(cfg, acc, event)

    assert action == RetryViaCommitHook(hook_output="commit hook_failed")


def test_decide_cm4_non_retryable_hook_failure_fails_with_staged_changes() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=2, pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("hook_failed"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(
        reason="commit_hook_failed",
        error="commit hook_failed",
        staged_changes_left=True,
        check_failures=True,
    )


def test_decide_cm5_non_hook_commit_failure_fails() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = CommitDone(status=None, commit_failed=_FakeCommitFailed("nothing_to_commit"))

    action = decide(cfg, acc, event)

    assert action == ExitFailed(reason="commit_failed", error="commit nothing_to_commit")


def test_decide_cm2_clear_skipped_no_changes_exits_clear() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        iteration=1,
        pending_check_failures="",
        last_review_status="clear",
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == ExitClear(reason="no_changes_after_remediation")


def test_decide_cm2_findings_skipped_no_changes_exits_findings() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        iteration=1,
        pending_check_failures="",
        last_review_status="findings",
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == ExitFindings(reason="no_changes_after_remediation")


def test_decide_cm2_unknown_skipped_no_changes_exits_unknown() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(
        iteration=1,
        pending_check_failures="",
        last_review_status="unknown",
    )
    event = CommitDone(status="skipped_no_changes")

    action = decide(cfg, acc, event)

    assert action == ExitUnknown(reason="no_changes_after_remediation")


def test_decide_cm1_successful_commit_continues() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", True)
    acc = LoopAccumulator(iteration=1, pending_check_failures="")
    event = CommitDone(status="committed")

    action = decide(cfg, acc, event)

    assert action == Continue()


def test_decide_nf1_no_final_review_exits_unknown_with_check_failure_flag() -> None:
    cfg = ConfigSnapshot(3, True, True, "fail", False)
    acc = LoopAccumulator(iteration=3, pending_check_failures="pytest failed")
    event = NoFinalReview()

    action = decide(cfg, acc, event)

    assert action == ExitUnknown(reason="max_iterations_reached", check_failures=True)
