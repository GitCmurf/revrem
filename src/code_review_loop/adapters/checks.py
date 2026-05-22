"""ChecksHarness adapter — wraps cli.run_checks behind the port (REVREM-TASK-003 B2b).

The adapter closes over LoopConfig at construction; the core passes only the
per-call variance (iteration) via ChecksRequest.  cli.run_checks retains its
full implementation as a legacy shim until C3; this adapter delegates to it via
a lazy import to keep the module-load import graph acyclic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.core.ports import ChecksOutcome, ChecksRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


class ChecksAdapter:
    """Implements ChecksHarness by delegating to the cli.run_checks shim."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
        from code_review_loop.cli import run_checks  # lazy — avoids circular import

        results, failed = run_checks(
            self._config,
            ctx.runner,
            request.iteration,
            ctx=ctx,
        )
        return ChecksOutcome(
            results=tuple(results),
            failed_commands=tuple(failed),
        )
