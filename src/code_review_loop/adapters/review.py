"""ReviewHarness adapter (REVREM-TASK-003 Wave C3a step 2).

The adapter owns the review-phase loop body. The implementation
(``run_codex_review`` + helpers) lives in ``adapters/_review_impl.py``;
the lazy ``from code_review_loop.cli import run_codex_review`` back-import
is gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.adapters._review_impl import run_codex_review
from code_review_loop.core.ports import ReviewOutcome, ReviewRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig


class ReviewAdapter:
    """Implements ReviewHarness via the in-module ``run_codex_review`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        status, result = run_codex_review(
            self._config,
            ctx.runner,
            request.artifact_label,
            display_label=request.display_label,
            ctx=ctx,
        )
        return ReviewOutcome(status=status, result=result)  # type: ignore[arg-type]
