"""CommitHarness adapter (REVREM-TASK-003 Wave C3a step 5).

The adapter owns the commit-phase body via ``adapters/_commit_impl``; the
lazy ``from code_review_loop.cli import run_commit`` back-import is gone.
``CommitFailed`` and ``RuntimeError`` propagate unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.adapters._commit_impl import run_commit
from code_review_loop.core.ports import CommitOutcome, CommitRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig


class CommitAdapter:
    """Implements CommitHarness via the in-module ``run_commit`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        status = run_commit(
            self._config,
            ctx.runner,
            request.iteration,
            retrying=request.retrying,
            ctx=ctx,
        )
        return CommitOutcome(status=status)  # type: ignore[arg-type]
