"""RemediationHarness adapter (REVREM-TASK-003 Wave C3a step 3).

The adapter owns the remediation-phase body via ``adapters/_remediation_impl``;
the lazy ``from code_review_loop.cli import run_remediation`` back-import is
gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.adapters._remediation_impl import run_remediation
from code_review_loop.core.ports import RemediationOutcome, RemediationRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


class RemediationAdapter:
    """Implements RemediationHarness via the in-module ``run_remediation`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        result = run_remediation(
            self._config,
            ctx.runner,
            request.iteration,
            request.remediation_input,
            resolved_route=request.resolved_route,
            ctx=ctx,
        )
        return RemediationOutcome(result=result)
