"""Final-review execution and bounded-recovery shell transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_review_loop.adapters.phase_support import _combined_output
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import EngineState, ReviewDone
from code_review_loop.core.ports import ReviewRequest, RunContext
from code_review_loop.core.review_interpretation import actionable_review_output
from code_review_loop.core.state import RunState


@dataclass(frozen=True)
class FinalReviewPhaseResult:
    state: EngineState
    cause: RuntimeError | None = None


def execute_final_review(
    config: LoopConfig,
    ctx: RunContext,
    run_state: RunState,
    engine_state: EngineState,
) -> FinalReviewPhaseResult:
    """Run the next uniquely named final review and preserve its recovery source."""

    recovery_index = max(0, engine_state.iteration - config.max_iterations)
    artifact_label = (
        "review-final"
        if recovery_index == 0
        else f"review-final-recovery-{recovery_index}"
    )
    try:
        outcome = ctx.phase_review.execute(
            ReviewRequest(artifact_label=artifact_label, display_label="final"),
            ctx,
        )
    except RuntimeError as exc:
        run_state.iterations.append({"iteration": "final", "review_failed": True})
        return FinalReviewPhaseResult(
            replace(
                engine_state,
                event=ReviewDone(is_final=True, status="unknown", exc=exc),
            ),
            cause=exc,
        )
    status, review = outcome.status, outcome.result
    acc = replace(
        engine_state.acc,
        last_review_output=actionable_review_output(_combined_output(review)),
        last_review_status=status,
        source_review_artifact=f"{artifact_label}.txt",
    )
    if status == "unknown" and not acc.pending_check_failures:
        run_state.iterations.append({"iteration": "final", "review_status": status})
    return FinalReviewPhaseResult(
        replace(engine_state, acc=acc, event=ReviewDone(is_final=True, status=status))
    )


def begin_final_review_remediation(
    run_state: RunState,
    engine_state: EngineState,
) -> EngineState:
    """Consume one recovery pass and re-enter the ordinary finding path."""

    iteration = engine_state.iteration + 1
    run_state.iterations.append(
        {
            "iteration": iteration,
            "review_status": "findings",
            "review_source": engine_state.acc.source_review_artifact,
            "final_review_remediation": True,
        }
    )
    acc = replace(
        engine_state.acc,
        resolved_route=None,
        remediation_result_returncode=None,
        remediation_duration=0.0,
        inner_check_retry_count=0,
        stale_review_resolved=False,
        stale_review_dirty="",
        stale_review_loaded=False,
    )
    return replace(
        engine_state,
        acc=acc,
        event=ReviewDone(is_final=False, status="findings"),
        iteration=iteration,
    )
