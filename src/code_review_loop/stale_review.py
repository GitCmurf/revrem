"""Helpers for validating intentionally reused stale review artifacts."""

from __future__ import annotations

from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import EngineState

STALE_REVIEW_RESOLVED_MARKER = "REVREM_STALE_REVIEW_STATUS: resolved"
STALE_REVIEW_STILL_APPLIES_MARKER = "REVREM_STALE_REVIEW_STATUS: still_applies"
STALE_REVIEW_UNKNOWN_MARKER = "REVREM_STALE_REVIEW_STATUS: unknown"
STALE_REVIEW_VALIDATION_HEADER = "STALE_REVIEW_VALIDATION:"


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
        "emit this compact block, with concrete file/test/command evidence:\n\n"
        f"{STALE_REVIEW_VALIDATION_HEADER}\n"
        "status: resolved\n"
        "findings_checked: <count>\n"
        "evidence:\n"
        "- <why the stale finding no longer applies>\n"
        f"{STALE_REVIEW_RESOLVED_MARKER}\n\n"
        "If any finding still applies, remediate it normally and do not emit "
        "the resolved marker.\n\n"
        f"{remediation_input}"
    )


def read_only_validation_prompt(review_input: str) -> str:
    return (
        "Read-only stale pending-review validation mode:\n"
        "The supplied review artifact came from a different HEAD/base than the "
        "current checkout. Validate whether each finding still applies to the "
        "current tree. Do not edit files. Do not run write-capable tools.\n\n"
        "Respond with this compact block and concrete file/test/command evidence:\n\n"
        f"{STALE_REVIEW_VALIDATION_HEADER}\n"
        "status: <resolved|still_applies|unknown>\n"
        "findings_checked: <count>\n"
        "evidence:\n"
        "- <why the finding is resolved, still applies, or cannot be determined>\n"
        "REVREM_STALE_REVIEW_STATUS: <resolved|still_applies|unknown>\n\n"
        "Use `resolved` only when all findings are already fixed in the current "
        "checkout. Use `still_applies` when any finding remains actionable. Use "
        "`unknown` only when the supplied evidence is insufficient to decide.\n\n"
        f"{review_input}"
    )


def contains_resolved_marker(output: str) -> bool:
    return STALE_REVIEW_RESOLVED_MARKER in output


def validation_status(output: str) -> str:
    if STALE_REVIEW_RESOLVED_MARKER in output:
        return "resolved"
    if STALE_REVIEW_STILL_APPLIES_MARKER in output:
        return "still_applies"
    if STALE_REVIEW_UNKNOWN_MARKER in output:
        return "unknown"
    return "unknown"


def validation_summary(output: str) -> str:
    start = output.find(STALE_REVIEW_VALIDATION_HEADER)
    if start < 0:
        return output.strip()
    marker_positions = [
        (output.find(marker, start), marker)
        for marker in (
            STALE_REVIEW_RESOLVED_MARKER,
            STALE_REVIEW_STILL_APPLIES_MARKER,
            STALE_REVIEW_UNKNOWN_MARKER,
        )
    ]
    marker_positions = [(index, marker) for index, marker in marker_positions if index >= 0]
    if not marker_positions:
        return output[start:].strip()
    marker_start, marker = min(marker_positions, key=lambda item: item[0])
    end = marker_start + len(marker)
    return output[start:end].strip()
