"""The typed run-state aggregate (REVREM-TASK-003 A3).

`RunState` replaces the untyped ``summary`` dict that the loop smears 60 writes
across. A3 is a deliberately narrow *shadow* step (the "(b1)" approach):

- RunState holds the **live** in-loop summary dict and iterations list — the
  same objects the loop still reads — so the ~46 ``summary[...]`` reads and the
  17 iteration mutations keep working unchanged during the transition.
- The scalar terminal writes (``final_status``, ``stopped_reason``, ``error``,
  ``latest_review_excerpt``, ``suppressed_findings_count``,
  ``pending_check_failures``, ``staged_changes_left``) move behind low-level
  transition methods, centralising the exit-determining writes in one place.
- ``to_dict()`` returns that live dict; ``write_summary`` augments it with the
  contract / artifact-path / budget fields at emit time — that augmentation is
  the reporting layer and is out of A3's scope.

Naming is intentionally low-level (one setter per write site). Semantic
transitions (``mark_clear``, ``mark_failed(reason)``) and an explicit
``RunOutcome`` are layered on in B3, once the branch→outcome survey exists.

This module is part of ``core`` and imports only the standard library
(Contract C4).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunState:
    """Aggregate shadowing the in-loop summary dict + iterations list."""

    _summary: dict[str, object]
    iterations: list[dict[str, object]]

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
        """Build the initial run state, mirroring the legacy summary literal."""
        iterations: list[dict[str, object]] = []
        summary: dict[str, object] = {
            "base": base,
            "git_state": git_state,
            "resume_config": resume_config,
            "run_id": run_id,
            "started_at": started_at,
            "profile": profile,
            "max_iterations": max_iterations,
            "artifact_dir": artifact_dir,
            "iterations": iterations,
            "commit_on_hook_failure": commit_on_hook_failure,
            "commit_no_verify": commit_on_hook_failure == "no-verify",
            "budgets": budgets,
            "final_status": "unknown",
            "initial_review_file": initial_review_file,
            "pending_check_failures": False,
            "stopped_reason": None,
        }
        return cls(_summary=summary, iterations=iterations)

    def to_dict(self) -> dict[str, object]:
        """Return the live summary dict (not a copy)."""
        return self._summary

    # --- scalar terminal-state transitions (low-level; B3 layers semantics) ---

    def set_final_status(self, value: str) -> None:
        self._summary["final_status"] = value

    def set_stopped_reason(self, value: str | None) -> None:
        self._summary["stopped_reason"] = value

    def set_error(self, value: str) -> None:
        self._summary["error"] = value

    def set_latest_review_excerpt(self, value: str) -> None:
        self._summary["latest_review_excerpt"] = value

    def set_suppressed_findings_count(self, value: int) -> None:
        self._summary["suppressed_findings_count"] = value

    def set_pending_check_failures(self, value: bool) -> None:
        self._summary["pending_check_failures"] = value

    def set_staged_changes_left(self, value: bool) -> None:
        self._summary["staged_changes_left"] = value
