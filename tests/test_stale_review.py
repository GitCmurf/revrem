from __future__ import annotations

from code_review_loop import stale_review


def _block(status: str, marker: str | None = None) -> str:
    marker = marker or status
    return (
        "STALE_REVIEW_VALIDATION:\n"
        f"status: {status}\n"
        "findings_checked: 1\n"
        "evidence:\n"
        "- evidence\n"
        f"REVREM_STALE_REVIEW_STATUS: {marker}\n"
    )


def test_validation_status_ignores_resolved_marker_in_stderr_prompt_echo() -> None:
    output = (
        _block("still_applies")
        + "\n[stderr]\n"
        + "Prompt template: REVREM_STALE_REVIEW_STATUS: resolved\n"
    )

    assert stale_review.validation_status(output) == "still_applies"
    assert stale_review.validation_summary(output) == _block("still_applies").strip()


def test_validation_status_ignores_still_applies_marker_in_stderr_prompt_echo() -> None:
    output = (
        _block("resolved")
        + "\n[stderr]\n"
        + "Prompt template: REVREM_STALE_REVIEW_STATUS: still_applies\n"
    )

    assert stale_review.validation_status(output) == "resolved"


def test_validation_status_ignores_marker_outside_validation_block() -> None:
    output = "Context mentions REVREM_STALE_REVIEW_STATUS: resolved\n\n" + _block("still_applies")

    assert stale_review.validation_status(output) == "still_applies"
    assert stale_review.validation_summary(output) == _block("still_applies").strip()


def test_validation_status_conflicting_status_and_marker_is_unknown() -> None:
    output = _block("still_applies", marker="resolved")

    assert stale_review.validation_status(output) == "unknown"


def test_validation_status_missing_block_is_unknown() -> None:
    output = "REVREM_STALE_REVIEW_STATUS: resolved\n"

    assert stale_review.validation_status(output) == "unknown"
