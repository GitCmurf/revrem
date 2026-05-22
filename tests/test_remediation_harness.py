"""Tests for the RemediationHarness adapter wiring (REVREM-TASK-003 B2d)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import code_review_loop.cli as MODULE
from code_review_loop.adapters.remediation import RemediationAdapter
from code_review_loop.clock import Clock
from code_review_loop.core.ports import (
    CommandResult,
    RemediationOutcome,
    RemediationRequest,
    RunContext,
)
from code_review_loop.core.routing_types import ResolvedRoute
from code_review_loop.identity import RunIdentity


def _ctx(runner=None, **kwargs: object) -> RunContext:
    return RunContext(
        clock=MagicMock(spec=Clock),
        identity=MagicMock(spec=RunIdentity),
        runner=runner if runner is not None else MagicMock(),
        **kwargs,  # type: ignore[arg-type]
    )


class TestRemediationAdapter:
    def test_dry_run_returns_outcome(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            dry_run=True,
        )
        runner = MagicMock(side_effect=AssertionError("no subprocess in dry-run"))
        ctx = _ctx(runner=runner)
        adapter = RemediationAdapter(config)

        outcome = adapter.execute(
            RemediationRequest(iteration=1, remediation_input="fix this"),
            ctx,
        )

        assert isinstance(outcome, RemediationOutcome)
        assert outcome.result.returncode == 0
        assert "DRY_RUN" in outcome.result.stdout
        runner.assert_not_called()

    def test_resolved_route_threaded_through(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        route = ResolvedRoute(route_tier="fast", harness="codex")
        ctx = _ctx(runner=MagicMock())
        adapter = RemediationAdapter(config)

        with patch("code_review_loop.cli.run_remediation") as mock_rem:
            mock_rem.return_value = CommandResult(["codex"], 0)
            outcome = adapter.execute(
                RemediationRequest(iteration=2, remediation_input="prompt", resolved_route=route),
                ctx,
            )

        mock_rem.assert_called_once()
        call_kwargs = mock_rem.call_args[1]
        assert call_kwargs.get("resolved_route") is route
        assert isinstance(outcome, RemediationOutcome)

    def test_runtime_error_propagates(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=MagicMock(return_value=CommandResult(["codex"], 1)))
        adapter = RemediationAdapter(config)

        with pytest.raises(RuntimeError):
            adapter.execute(
                RemediationRequest(iteration=1, remediation_input="fix"),
                ctx,
            )


class TestEngineDispatch:
    def test_harness_called_when_wired(self) -> None:
        fake_result = CommandResult(["codex"], 0, stdout="fixed\n")
        fake_outcome = RemediationOutcome(result=fake_result)

        class SentinelHarness:
            calls: list[RemediationRequest] = []

            def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
                SentinelHarness.calls.append(request)
                return fake_outcome

        sentinel = SentinelHarness()
        ctx = _ctx(phase_remediation=sentinel)
        request = RemediationRequest(iteration=1, remediation_input="the review output")

        if ctx.phase_remediation is not None:
            outcome = ctx.phase_remediation.execute(request, ctx)
        else:
            raise AssertionError("harness branch not taken")

        assert outcome is fake_outcome
        assert SentinelHarness.calls[0].remediation_input == "the review output"
