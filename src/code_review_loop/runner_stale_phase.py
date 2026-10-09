"""Stale-review validation orchestration for the runner shell."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_review_loop import budgets, stale_validation_status
from code_review_loop.adapters.phase_support import emit_loop_failure_event
from code_review_loop.adapters.stale_validation import run_stale_validation
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import EngineState, LoopAccumulator, StaleValidationDone
from code_review_loop.core.ports import RunContext
from code_review_loop.core.state import RunState
from code_review_loop.run_guards import assert_worktree_stable_before_remediation


@dataclass(frozen=True)
class StalePreflightResult:
    status: str
    acc: LoopAccumulator | None = None
    summary: str = ""


@dataclass(frozen=True)
class StaleValidationPhaseResult:
    state: EngineState
    cause: BaseException | None = None
    validation_output: str = ""
    status_before: tuple[str, ...] | None = None


def execute_stale_validation_phase(
    *,
    config: LoopConfig,
    ctx: RunContext,
    clock: Clock,
    run_state: RunState,
    engine_state: EngineState,
    expected_head: str | None,
) -> StaleValidationPhaseResult:
    iteration = engine_state.iteration
    validation_input = engine_state.acc.last_review_output
    if engine_state.acc.pending_check_failures:
        validation_input = engine_state.acc.pending_check_failures + "\n\n" + validation_input
    status_before: tuple[str, ...] | None = None
    try:
        status_before = stale_validation_status.non_artifact_status_snapshot(config, ctx)
        assert_worktree_stable_before_remediation(
            config,
            ctx,
            engine_state,
            expected_head=expected_head,
        )
        started_at = clock.monotonic()
        preflight = run_stale_preflight(
            config=config,
            ctx=ctx,
            clock=clock,
            iteration=iteration,
            remediation_input=validation_input,
            acc=replace(engine_state.acc, remediation_input=validation_input),
            started_at=started_at,
            status_before=status_before,
        )
        if preflight.acc is not None:
            run_state.iterations[-1]["stale_review_resolved"] = True
            return StaleValidationPhaseResult(
                state=replace(
                    engine_state,
                    acc=preflight.acc,
                    event=StaleValidationDone(status="resolved"),
                ),
                validation_output=preflight.summary,
                status_before=status_before,
            )
        run_state.iterations[-1]["stale_review_still_applies"] = True
        return StaleValidationPhaseResult(
            state=replace(
                engine_state,
                acc=replace(engine_state.acc, remediation_input=validation_input),
                event=StaleValidationDone(status="still_applies"),
            ),
            status_before=status_before,
        )
    except budgets.BudgetExceeded:
        raise
    except Exception as exc:
        run_state.iterations[-1]["stale_validation_failed"] = True
        emit_loop_failure_event(
            config,
            phase="stale-validation",
            iteration=iteration,
            reason="stale_validation_failed",
            error=str(exc),
            ctx=ctx,
        )
        return StaleValidationPhaseResult(
            state=replace(
                engine_state,
                event=StaleValidationDone(status="unknown", exc=exc),
            ),
            cause=exc,
            status_before=status_before,
        )


def run_stale_preflight(
    *,
    config: LoopConfig,
    ctx: RunContext,
    clock: Clock,
    iteration: int,
    remediation_input: str,
    acc: LoopAccumulator,
    started_at: float,
    status_before: tuple[str, ...] | None,
) -> StalePreflightResult:
    validation = run_stale_validation(
        config,
        ctx,
        iteration=iteration,
        validation_input=remediation_input,
    )
    if validation.status != "resolved":
        return StalePreflightResult(status=validation.status)
    resolved_acc = replace(
        acc,
        remediation_input=remediation_input,
        remediation_result_returncode=validation.result.returncode,
        remediation_duration=clock.monotonic() - started_at,
        stale_review_resolved=True,
    )
    dirty = stale_validation_status.dirty_message(config, ctx, status_before)
    if dirty:
        raise RuntimeError(dirty)
    return StalePreflightResult(
        status=validation.status,
        acc=resolved_acc,
        summary=validation.summary,
    )
