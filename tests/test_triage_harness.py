"""Tests for the TriageHarness adapter wiring (REVREM-TASK-003 B2e)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from support.phase_harnesses import phase_harness_kwargs

import code_review_loop.runner as runner_mod
from code_review_loop.adapters.triage import TriageAdapter
from code_review_loop.clock import Clock
from code_review_loop.core.ports import (
    RunContext,
    TriageOutcome,
    TriageRequest,
)
from code_review_loop.identity import RunIdentity


def _ctx(runner=None, **kwargs: object) -> RunContext:
    return RunContext(
        clock=MagicMock(spec=Clock),
        identity=MagicMock(spec=RunIdentity),
        runner=runner if runner is not None else MagicMock(),
        **phase_harness_kwargs(**kwargs),  # type: ignore[arg-type]
    )


class TestTriageAdapter:
    def test_dry_run_returns_outcome(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            dry_run=True,
            triage_enabled=True,
        )
        runner = MagicMock(side_effect=AssertionError("no subprocess in dry-run"))
        ctx = _ctx(runner=runner)
        adapter = TriageAdapter(config)

        outcome = adapter.execute(
            TriageRequest(iteration=1, run_id="r1", source_review_artifact="review-1.txt", review_output="findings"),
            ctx,
        )

        assert isinstance(outcome, TriageOutcome)
        runner.assert_not_called()

    def test_all_fields_passed_through(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            triage_enabled=True,
        )
        ctx = _ctx(runner=MagicMock())
        adapter = TriageAdapter(config)

        # REVREM-TASK-003 Wave C3a step 4: run_triage now lives in
        # ``adapters.triage`` and is imported by ``adapters.triage``
        # directly. Patch the binding the adapter actually calls.
        with patch("code_review_loop.adapters.triage.run_triage") as mock_triage:
            mock_triage.return_value = ("handoff text", 0, False, None)
            outcome = adapter.execute(
                TriageRequest(
                    iteration=2,
                    run_id="run-abc",
                    source_review_artifact="review-2.txt",
                    review_output="big review",
                ),
                ctx,
            )

        args, kwargs = mock_triage.call_args
        assert args[2] == 2  # iteration
        assert args[3] == "run-abc"  # run_id
        assert args[4] == "review-2.txt"  # source_review_artifact
        assert args[5] == "big review"  # review_output
        assert outcome.handoff == "handoff text"
        assert outcome.is_clear is False
        assert outcome.payload is None

    def test_clear_triage_outcome(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            triage_enabled=True,
        )
        ctx = _ctx(runner=MagicMock())
        adapter = TriageAdapter(config)

        with patch("code_review_loop.adapters.triage.run_triage") as mock_triage:
            mock_triage.return_value = ("", 3, True, {"confirmed_findings": []})
            outcome = adapter.execute(
                TriageRequest(iteration=1, run_id="r", source_review_artifact="a.txt", review_output="ok"),
                ctx,
            )

        assert outcome.is_clear is True
        assert outcome.suppressed_count == 3
        assert outcome.payload == {"confirmed_findings": []}


class TestEngineDispatch:
    def test_harness_called_when_wired(self) -> None:
        fake_outcome = TriageOutcome(handoff="triage text", suppressed_count=0, is_clear=False, payload=None)

        class SentinelHarness:
            calls: list[TriageRequest] = []

            def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
                SentinelHarness.calls.append(request)
                return fake_outcome

        sentinel = SentinelHarness()
        ctx = _ctx(phase_triage=sentinel)
        request = TriageRequest(iteration=1, run_id="r", source_review_artifact="a.txt", review_output="x")

        outcome = ctx.phase_triage.execute(request, ctx)

        assert outcome is fake_outcome
        assert SentinelHarness.calls[0].run_id == "r"
