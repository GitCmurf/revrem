"""ReviewHarness adapter — wraps cli.run_codex_review (REVREM-TASK-003 B2f).

The adapter closes over LoopConfig at construction; the core passes
artifact_label and optional display_label via ReviewRequest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.core.ports import ReviewOutcome, ReviewRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


class ReviewAdapter:
    """Implements ReviewHarness by delegating to the cli.run_codex_review shim."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        from code_review_loop.cli import run_codex_review  # lazy — avoids circular import

        status, result = run_codex_review(
            self._config,
            ctx.runner,
            request.artifact_label,
            display_label=request.display_label,
            ctx=ctx,
        )
        return ReviewOutcome(status=status, result=result)  # type: ignore[arg-type]
