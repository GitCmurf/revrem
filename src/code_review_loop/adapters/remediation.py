"""RemediationHarness adapter — wraps cli.run_remediation (REVREM-TASK-003 B2d).

The adapter closes over LoopConfig at construction; the core passes iteration,
remediation_input, and optional resolved_route via RemediationRequest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.core.ports import RemediationOutcome, RemediationRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


class RemediationAdapter:
    """Implements RemediationHarness by delegating to the cli.run_remediation shim."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        from code_review_loop.cli import run_remediation  # lazy — avoids circular import

        result = run_remediation(
            self._config,
            ctx.runner,
            request.iteration,
            request.remediation_input,
            resolved_route=request.resolved_route,
            ctx=ctx,
        )
        return RemediationOutcome(result=result)
