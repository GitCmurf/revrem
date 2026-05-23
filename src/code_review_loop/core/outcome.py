"""RunOutcome ADT — all terminal states of a review-remediate run (REVREM-TASK-003 B3c).

Every branch in _run_loop that does not loop back produces exactly one of these.
``outcome_to_exit_code()`` (B3c-ii) maps this to an integer exit code without
reading ``stopped_reason`` strings.

The ``reason`` field is the ``stopped_reason`` value written to the JSON summary;
it is used only for artifact serialisation, never for control flow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutcomeClear:
    """Run finished with no actionable findings (final_status=clear)."""

    reason: str  # stopped_reason value
    excerpt: str = ""
    suppressed_findings_count: int = 0


@dataclass(frozen=True)
class OutcomeFailed:
    """Run terminated with an error (final_status=error)."""

    reason: str  # stopped_reason value
    error: str
    staged_changes_left: bool = False
    check_failures: bool = False


@dataclass(frozen=True)
class OutcomeFindings:
    """Run exhausted iterations with findings remaining (final_status=findings)."""

    reason: str  # stopped_reason value
    check_failures: bool = False


@dataclass(frozen=True)
class OutcomeUnknown:
    """Run exhausted iterations; final review status indeterminate (final_status=unknown)."""

    reason: str  # stopped_reason value
    check_failures: bool = False


RunOutcome = OutcomeClear | OutcomeFailed | OutcomeFindings | OutcomeUnknown
