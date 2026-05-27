from __future__ import annotations

from pathlib import Path

from code_review_loop import budgets, events
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import ConfigSnapshot
from code_review_loop.core.ports import RunContext
from code_review_loop.core.state import RunState
from code_review_loop.runner_shell import run_iterations
from tests.support.fakes import FIXED_ISO, FIXED_RUN_ID, FakeClock, FakeRunIdentity
from tests.support.headless import (
    RecordingProcessRunner,
    RecordingRemediationHarness,
    SequencedChecksHarness,
    SequencedReviewHarness,
    StaticCommitHarness,
    StaticTriageHarness,
)


def _config(tmp_path: Path, *, max_iterations: int = 1, triage_enabled: bool = True) -> LoopConfig:
    return LoopConfig(
        base="main",
        max_iterations=max_iterations,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        triage_enabled=triage_enabled,
    )


def _snapshot(config: LoopConfig) -> ConfigSnapshot:
    return ConfigSnapshot(
        max_iterations=config.max_iterations,
        triage_enabled=config.triage_enabled,
        commit_after_remediation=config.commit_after_remediation,
        commit_on_hook_failure=config.commit_on_hook_failure,
        final_review=config.final_review,
    )


def _state(config: LoopConfig) -> RunState:
    return RunState.create(
        base=config.base,
        git_state={},
        resume_config={},
        run_id=FIXED_RUN_ID,
        started_at=FIXED_ISO,
        profile=None,
        max_iterations=config.max_iterations,
        artifact_dir=str(config.artifact_dir),
        commit_on_hook_failure=config.commit_on_hook_failure,
        budgets={},
        initial_review_file=None,
    )


def _context(
    config: LoopConfig,
    *,
    review: SequencedReviewHarness,
    remediation: RecordingRemediationHarness | None = None,
    checks: SequencedChecksHarness | None = None,
    triage: StaticTriageHarness | None = None,
) -> tuple[RunContext, events.JsonlSink]:
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    clock = FakeClock()
    sink = events.JsonlSink(config.artifact_dir, FIXED_RUN_ID, clock=clock)
    ctx = RunContext(
        clock=clock,
        identity=FakeRunIdentity(),
        runner=RecordingProcessRunner(),
        event_sink=sink,
        budget_state=budgets.BudgetState(started_at_monotonic=0),
        progress_reporter=None,
        phase_checks=checks or SequencedChecksHarness(),
        phase_commit=StaticCommitHarness(),
        phase_remediation=remediation or RecordingRemediationHarness(),
        phase_review=review,
        phase_triage=triage or StaticTriageHarness(is_clear=False),
    )
    return ctx, sink


def test_runner_shell_executes_happy_path_without_cli(tmp_path: Path) -> None:
    config = _config(tmp_path, max_iterations=1)
    review = SequencedReviewHarness(["findings", "clear"])
    ctx, sink = _context(config, review=review)
    clock = ctx.clock
    try:
        state = _state(config)

        result = run_iterations(
            config=config,
            state=state,
            clock=clock,
            ctx=ctx,
            snap=_snapshot(config),
            initial_review_output="",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "review_clear"
    assert result.cause is None
    assert [iteration["iteration"] for iteration in state.iterations] == [1]
    assert state.iterations[0]["review_status"] == "findings"
    assert result.last_review_output


def test_runner_shell_carries_check_failure_into_retry(tmp_path: Path) -> None:
    config = _config(tmp_path, max_iterations=2, triage_enabled=False)
    review = SequencedReviewHarness(["findings", "findings", "clear"])
    remediation = RecordingRemediationHarness()
    checks = SequencedChecksHarness([("pytest tests/",), ()])
    ctx, sink = _context(config, review=review, remediation=remediation, checks=checks)
    clock = ctx.clock
    try:
        state = _state(config)

        result = run_iterations(
            config=config,
            state=state,
            clock=clock,
            ctx=ctx,
            snap=_snapshot(config),
            initial_review_output="",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "review_clear"
    assert [iteration["iteration"] for iteration in state.iterations] == [1, 2]
    assert [request.iteration for request in checks.calls] == [1, 2]
    assert "pytest tests/ failed" in remediation.calls[1].remediation_input
