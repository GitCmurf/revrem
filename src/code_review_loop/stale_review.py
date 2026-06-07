"""Helpers for validating intentionally reused stale review artifacts."""

from __future__ import annotations

from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import EngineState

STALE_REVIEW_STATUS_VALUES = ("resolved", "still_applies", "unknown")
STALE_REVIEW_RESOLVED_MARKER = "REVREM_STALE_REVIEW_STATUS: resolved"
STALE_REVIEW_STILL_APPLIES_MARKER = "REVREM_STALE_REVIEW_STATUS: still_applies"
STALE_REVIEW_UNKNOWN_MARKER = "REVREM_STALE_REVIEW_STATUS: unknown"
STALE_REVIEW_VALIDATION_HEADER = "STALE_REVIEW_VALIDATION:"
STDERR_SENTINEL = "\n[stderr]\n"


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
    return validation_status(output) == "resolved"


def validation_status(output: str) -> str:
    block = _validation_block(output)
    if block is None:
        return "unknown"
    status_line_value = _status_line_value(block)
    marker_value = _marker_value(block)
    if status_line_value and marker_value and status_line_value != marker_value:
        return "unknown"
    return status_line_value or marker_value or "unknown"


def validation_summary(output: str) -> str:
    block = _validation_block(output)
    return block if block is not None else _stdout_only(output).strip()


def _stdout_only(output: str) -> str:
    return output.split(STDERR_SENTINEL, 1)[0]


def _validation_block(output: str) -> str | None:
    stdout = _stdout_only(output)
    start = stdout.find(STALE_REVIEW_VALIDATION_HEADER)
    if start < 0:
        return None
    marker_positions = [
        (stdout.find(f"REVREM_STALE_REVIEW_STATUS: {value}", start), value)
        for value in STALE_REVIEW_STATUS_VALUES
    ]
    marker_positions = [(index, value) for index, value in marker_positions if index >= 0]
    if marker_positions:
        marker_start, value = min(marker_positions, key=lambda item: item[0])
        marker = f"REVREM_STALE_REVIEW_STATUS: {value}"
        return stdout[start : marker_start + len(marker)].strip()
    return stdout[start:].strip()


def _status_line_value(block: str) -> str | None:
    for line in block.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "status":
            normalized = value.strip().lower()
            if normalized in STALE_REVIEW_STATUS_VALUES:
                return normalized
            return None
    return None


def _marker_value(block: str) -> str | None:
    earliest: tuple[int, str] | None = None
    for value in STALE_REVIEW_STATUS_VALUES:
        marker = f"REVREM_STALE_REVIEW_STATUS: {value}"
        index = block.find(marker)
        if index >= 0 and (earliest is None or index < earliest[0]):
            earliest = (index, value)
    return earliest[1] if earliest else None
