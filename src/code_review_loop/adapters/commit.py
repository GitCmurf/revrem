"""CommitHarness adapter — wraps cli.run_commit behind the port (REVREM-TASK-003 B2c).

The adapter closes over LoopConfig at construction; the core passes only the
per-call variance (iteration, retrying) via CommitRequest.  CommitFailed and
RuntimeError propagate unchanged — the harness contract matches the shim's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.core.ports import CommitOutcome, CommitRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


class CommitAdapter:
    """Implements CommitHarness by delegating to the cli.run_commit shim."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        from code_review_loop.cli import run_commit  # lazy — avoids circular import

        status = run_commit(
            self._config,
            ctx.runner,
            request.iteration,
            retrying=request.retrying,
            ctx=ctx,
        )
        return CommitOutcome(status=status)  # type: ignore[arg-type]
