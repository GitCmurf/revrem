"""Stale-review validation orchestration for the runner shell."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_review_loop import stale_validation_status
from code_review_loop.adapters.stale_validation import run_stale_validation
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import LoopAccumulator
from code_review_loop.core.ports import RunContext


@dataclass(frozen=True)
class StalePreflightResult:
    status: str
    acc: LoopAccumulator | None = None
    summary: str = ""


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
