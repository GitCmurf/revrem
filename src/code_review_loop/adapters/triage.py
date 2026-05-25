"""TriageHarness adapter (REVREM-TASK-003 Wave C3a step 4).

The adapter owns the triage-phase body via ``adapters/_triage_impl``; the lazy
``from code_review_loop.cli import run_triage`` back-import is gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.adapters._triage_impl import run_triage
from code_review_loop.core.ports import RunContext, TriageOutcome, TriageRequest

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig


class TriageAdapter:
    """Implements TriageHarness via the in-module ``run_triage`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
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
