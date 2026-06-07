"""Routing helpers for the runner shell."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import LoopAccumulator
from code_review_loop.core.ports import RunContext
from code_review_loop.routing_artifacts import resolve_and_record_routing
from code_review_loop.triage import RoutingContextCache


def resolve_routing_accumulator(
    *,
    config: LoopConfig,
    ctx: RunContext,
    run_id: str,
    iteration: int,
    triage_payload: dict[str, Any],
    acc: LoopAccumulator,
    cache: RoutingContextCache,
) -> LoopAccumulator:
    resolution = resolve_and_record_routing(
        config=config,
        ctx=ctx,
        run_id=run_id,
        iteration=iteration,
        triage_payload=triage_payload,
        remediation_input=acc.remediation_input,
        failed_check_names=acc.failed_check_names,
        cache=cache,
    )
    return replace(
        acc,
        resolved_route=resolution.resolved_route,
        remediation_input=resolution.remediation_input,
    )
