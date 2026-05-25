"""ChecksHarness adapter for the verification-check phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.adapters._checks_impl import run_checks
from code_review_loop.core.ports import ChecksOutcome, ChecksRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig


class ChecksAdapter:
    """Implements ChecksHarness via the in-module ``run_checks`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
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
