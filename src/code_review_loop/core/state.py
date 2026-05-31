"""Typed run-state aggregate (REVREM-TASK-003 A3/C3c)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)


@dataclass
class RunState:
    """Aggregate for loop-owned state with summary as a projection."""

    base: str
    git_state: dict[str, object]
    resume_config: dict[str, object]
    run_id: str
    started_at: str
    profile: str | None
    max_iterations: int
    artifact_dir: str
    commit_on_hook_failure: str
    budgets: dict[str, object]
    initial_review_file: str | None
    iterations: list[dict[str, object]]
    final_status: str = "unknown"
    pending_check_failures: bool = False
    stopped_reason: str | None = None
    error: str | None = None
    latest_review_excerpt: str | None = None
    suppressed_findings_count: int = 0
    staged_changes_left: bool = False

    @classmethod
    def create(
        cls,
        *,
        base: str,
        git_state: dict[str, object],
        resume_config: dict[str, object],
        run_id: str,
        started_at: str,
        profile: str | None,
        max_iterations: int,
        artifact_dir: str,
        commit_on_hook_failure: str,
        budgets: dict[str, object],
        initial_review_file: str | None,
    ) -> RunState:
        """Build the initial run state."""
        return cls(
            base=base,
            git_state=git_state,
            resume_config=resume_config,
            run_id=run_id,
            started_at=started_at,
            profile=profile,
            max_iterations=max_iterations,
            artifact_dir=artifact_dir,
            commit_on_hook_failure=commit_on_hook_failure,
            budgets=budgets,
            initial_review_file=initial_review_file,
            iterations=[],
        )

    def to_dict(self) -> dict[str, object]:
        """Project current run state into the summary JSON shape."""
        summary: dict[str, object] = {
            "base": self.base,
            "git_state": dict(self.git_state),
            "resume_config": dict(self.resume_config),
            "run_id": self.run_id,
            "started_at": self.started_at,
            "profile": self.profile,
            "max_iterations": self.max_iterations,
            "artifact_dir": self.artifact_dir,
            "iterations": self.iterations,
            "commit_on_hook_failure": self.commit_on_hook_failure,
            "commit_no_verify": self.commit_on_hook_failure == "no-verify",
            "budgets": dict(self.budgets),
            "final_status": self.final_status,
            "initial_review_file": self.initial_review_file,
            "pending_check_failures": self.pending_check_failures,
            "stopped_reason": self.stopped_reason,
        }
        if self.error is not None:
            summary["error"] = self.error
        if self.latest_review_excerpt:
            summary["latest_review_excerpt"] = self.latest_review_excerpt
        if self.suppressed_findings_count:
            summary["suppressed_findings_count"] = self.suppressed_findings_count
        if self.staged_changes_left:
            summary["staged_changes_left"] = True
        return summary

    # --- semantic terminal-state transitions ---

    def mark_outcome(
        self,
        outcome: RunOutcome,
        *,
        excerpt: str = "",
    ) -> None:
        """Apply one terminal outcome to the summary projection."""
        if not isinstance(outcome, (OutcomeClear, OutcomeFailed, OutcomeFindings, OutcomeUnknown)):
            assert_never(outcome)
        if excerpt:
            self.latest_review_excerpt = excerpt
        elif isinstance(outcome, OutcomeClear) and outcome.excerpt:
            self.latest_review_excerpt = outcome.excerpt

        if isinstance(outcome, OutcomeClear):
            self.mark_clear(outcome.reason, suppressed_findings_count=outcome.suppressed_findings_count)
            return
        if isinstance(outcome, OutcomeFailed):
            self.mark_failed(
                outcome.reason,
                outcome.error,
                staged_changes_left=outcome.staged_changes_left,
                check_failures=outcome.check_failures,
            )
            return
        if isinstance(outcome, OutcomeFindings):
            self.mark_findings(outcome.reason, check_failures=outcome.check_failures)
            return
        if isinstance(outcome, OutcomeUnknown):
            self.mark_unknown(outcome.reason, check_failures=outcome.check_failures)
            return

    def mark_clear(self, reason: str, *, suppressed_findings_count: int = 0) -> None:
        self.final_status = "clear"
        self.stopped_reason = reason
        if suppressed_findings_count:
            self.set_suppressed_findings_count(suppressed_findings_count)

    def mark_failed(
        self,
        reason: str,
        error: str,
        *,
        staged_changes_left: bool = False,
        check_failures: bool = False,
    ) -> None:
        self.final_status = "error"
        self.stopped_reason = reason
        self.error = error
        if staged_changes_left:
            self.staged_changes_left = True
        if check_failures:
            self.set_pending_check_failures(True)

    def mark_findings(self, reason: str, *, check_failures: bool = False) -> None:
        self.final_status = "findings"
        self.stopped_reason = reason
        if check_failures:
            self.set_pending_check_failures(True)

    def mark_unknown(self, reason: str, *, check_failures: bool = False) -> None:
        self.final_status = "unknown"
        self.stopped_reason = reason
        if check_failures:
            self.set_pending_check_failures(True)

    # --- scalar mid-run transitions ---

    def set_suppressed_findings_count(self, value: int) -> None:
        self.suppressed_findings_count = value

    def set_pending_check_failures(self, value: bool) -> None:
        self.pending_check_failures = value
