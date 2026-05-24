"""ChecksHarness adapter (REVREM-TASK-003 Wave C3a step 1).

The adapter owns the run-loop body for the check phase. The implementation
(plus its phase-specific helpers and project-surface markers) lives in
``adapters/_checks_impl.py`` so ``code_review_loop.cli.run_checks`` can stay
as a thin shim re-exporting the same callable, preserving the public
signature ``run_checks(config, runner, iteration, ctx=None) -> (results, failed)``
and the ``MODULE.run_checks`` monkeypatch surface that existing tests rely on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_review_loop.adapters._checks_impl import run_checks
from code_review_loop.core.ports import ChecksOutcome, ChecksRequest, RunContext

if TYPE_CHECKING:
    from code_review_loop.cli import LoopConfig


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
