"""Helpers for validating intentionally reused stale review artifacts."""

from __future__ import annotations

from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import EngineState

STALE_REVIEW_RESOLVED_MARKER = "REVREM_STALE_REVIEW_STATUS: resolved"


def should_validate_stale_review(
    config: LoopConfig,
    engine_state: EngineState,
    *,
    initial_review_output: str,
) -> bool:
    return (
        config.initial_review_mode == "stale"
        and engine_state.iteration == 1
        and bool(initial_review_output)
        and not engine_state.acc.pending_check_failures
        and not engine_state.acc.commit_retry
        and engine_state.acc.inner_check_retry_count == 0
    )


def validation_prompt(remediation_input: str) -> str:
    return (
        "Stale pending-review validation mode:\n"
        "The supplied review artifact came from a different HEAD/base than the "
        "current checkout. Before editing, verify each finding against the "
        "current tree. If the finding is already resolved, make no edits and "
        f"include `{STALE_REVIEW_RESOLVED_MARKER}` plus the command/file "
        "evidence that proves it. If the finding still applies, remediate it "
        "normally and do not emit the resolved marker.\n\n"
        f"{remediation_input}"
    )


def contains_resolved_marker(output: str) -> bool:
    return STALE_REVIEW_RESOLVED_MARKER in output
