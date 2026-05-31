"""Translate application calls into CLI exit decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from code_review_loop import application
from code_review_loop.core.outcome import OutcomeFailed, outcome_to_exit_code
from code_review_loop.runtime import RunLoopFailed


@dataclass(frozen=True)
class ApplicationExit:
    exit_code: int
    summary: dict[str, object]
    error: str | None = None
    cancelled: bool = False


def map_application_call(
    call: Callable[[], application.ReviewLoopResult],
    *,
    expected_errors: tuple[type[Exception], ...] = (),
    expected_error_exit_code: int = 1,
) -> ApplicationExit:
    """Run an application call and map its typed outcome to one CLI exit code."""

    try:
        result = call()
    except RunLoopFailed as exc:
        return ApplicationExit(
            exit_code=outcome_to_exit_code(exc.outcome),
            summary=exc.summary,
            error=str(exc),
        )
    except KeyboardInterrupt:
        outcome = OutcomeFailed(reason="cancelled", error="cancelled by operator")
        return ApplicationExit(
            exit_code=outcome_to_exit_code(outcome),
            summary={},
            error="Cancelled by user.",
            cancelled=True,
        )
    except expected_errors as exc:
        return ApplicationExit(
            exit_code=expected_error_exit_code,
            summary={},
            error=str(exc),
        )
    except Exception as exc:
        return ApplicationExit(
            exit_code=1,
            summary={},
            error=str(exc),
        )
    return ApplicationExit(
        exit_code=outcome_to_exit_code(result.outcome),
        summary=result.to_dict(),
    )
