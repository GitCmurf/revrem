"""TriageHarness adapter — wraps cli.run_triage (REVREM-TASK-003 B2e).

The adapter closes over LoopConfig at construction; the core passes
iteration, run_id, source_review_artifact, and review_output via TriageRequest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.core.ports import TriageOutcome, TriageRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


class TriageAdapter:
    """Implements TriageHarness by delegating to the cli.run_triage shim."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
        from code_review_loop.cli import run_triage  # lazy — avoids circular import

        handoff, suppressed_count, is_clear, payload = run_triage(
            self._config,
            ctx.runner,
            request.iteration,
            request.run_id,
            request.source_review_artifact,
            request.review_output,
            ctx=ctx,
        )
        return TriageOutcome(
            handoff=handoff,
            suppressed_count=suppressed_count,
            is_clear=is_clear,
            payload=payload,
        )
