from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from code_review_loop import budgets, events, profiles
from code_review_loop.adapters.phase_support import CommitFailed
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import ConfigSnapshot
from code_review_loop.core.ports import CommandResult, CommitOutcome, CommitRequest, RunContext
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
    commit: StaticCommitHarness | None = None,
    runner: RecordingProcessRunner | None = None,
    git_head_at_start: str | None = None,
) -> tuple[RunContext, events.JsonlSink]:
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    clock = FakeClock()
    sink = events.JsonlSink(config.artifact_dir, FIXED_RUN_ID, clock=clock)
    ctx = RunContext(
        clock=clock,
        identity=FakeRunIdentity(),
        runner=runner or RecordingProcessRunner(),
        event_sink=sink,
        budget_state=budgets.BudgetState(started_at_monotonic=0),
        progress_reporter=None,
        phase_checks=checks or SequencedChecksHarness(),
        phase_commit=commit or StaticCommitHarness(),
        phase_remediation=remediation or RecordingRemediationHarness(),
        phase_review=review,
        phase_triage=triage or StaticTriageHarness(is_clear=False),
        git_head_at_start=git_head_at_start,
    )
    return ctx, sink


class HookRetryCommitHarness:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path
        self.calls: list[CommitRequest] = []

    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        self.calls.append(request)
        if len(self.calls) == 1:
            raise CommitFailed(
                iteration=request.iteration,
                kind="hook_failed",
                artifact_path=self.artifact_path,
                output="Running mypy on staged Python files...\nFound 1 error in 1 file\n",
            )
        return CommitOutcome(status="committed")


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
    records, _ = events.read_events(config.artifact_dir / "events.jsonl")
    assert [record.kind for record in records] == []


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


def test_runner_shell_dense_commit_hook_retry_path_fits_step_budget(tmp_path: Path) -> None:
    config = replace(
        _config(tmp_path, max_iterations=2, triage_enabled=False),
        commit_after_remediation=True,
    )
    review = SequencedReviewHarness(["findings", "findings", "clear"])
    remediation = RecordingRemediationHarness()
    checks = SequencedChecksHarness([(), ()])
    commit = HookRetryCommitHarness(config.artifact_dir / "commit-1.txt")
    ctx, sink = _context(config, review=review, remediation=remediation, checks=checks, commit=commit)
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
    assert [request.iteration for request in commit.calls] == [1, 2]
    assert [request.retrying for request in commit.calls] == [False, True]
    assert len(remediation.calls) == 2
    assert "Commit hook failure" in remediation.calls[1].remediation_input
    assert "Running mypy" in remediation.calls[1].remediation_input
    assert [iteration["commit_status"] for iteration in state.iterations] == ["hook_failed", "committed"]


def test_runner_shell_stops_before_remediation_when_worktree_changes_during_review(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
    )
    review = SequencedReviewHarness(["findings"])
    remediation = RecordingRemediationHarness()
    process_runner = RecordingProcessRunner(
        {
            "rev-parse": CommandResult(["git", "rev-parse", "HEAD"], 0, stdout="start-head\n"),
            "status": CommandResult(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                0,
                stdout=" M src/concurrent.py\n",
            ),
        }
    )
    ctx, sink = _context(
        config,
        review=review,
        remediation=remediation,
        runner=process_runner,
        git_head_at_start="start-head",
    )
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

    assert result.outcome.reason == "remediation_failed"
    assert "worktree changed during run before remediation" in str(result.cause)
    assert "src/concurrent.py" in str(result.cause)
    assert remediation.calls == []


def test_runner_shell_stops_before_remediation_when_head_moves_during_review(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
    )
    review = SequencedReviewHarness(["findings"])
    remediation = RecordingRemediationHarness()
    process_runner = RecordingProcessRunner(
        {
            "rev-parse": CommandResult(["git", "rev-parse", "HEAD"], 0, stdout="new-head\n"),
            "status": CommandResult(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                0,
                stdout="",
            ),
        }
    )
    ctx, sink = _context(
        config,
        review=review,
        remediation=remediation,
        runner=process_runner,
        git_head_at_start="start-head",
    )
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

    assert result.outcome.reason == "remediation_failed"
    assert "HEAD moved from start-head to new-head" in str(result.cause)
    assert remediation.calls == []


def test_runner_shell_records_v2_routing_artifacts_and_events(tmp_path: Path) -> None:
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(enabled=True, default_route="frontier"),
            routes={"frontier": profiles.TriageRouteConfig(harness="codex", model="fake-clear")},
        ),
    )
    config = _config(tmp_path, max_iterations=1, triage_enabled=True)
    config = replace(
        config,
        triage_contract="v2",
        profile_v2=profile,
        remediation_harness="fake",
    )
    review = SequencedReviewHarness(["findings", "clear"])
    triage = StaticTriageHarness(
        handoff="fix it",
        payload={
            "schema_version": "2.0",
            "run_id": FIXED_RUN_ID,
            "source_review_artifact": "review-1.txt",
            "confirmed_findings": [
                {"summary": "Fix auth check", "severity": "P1", "files": ["auth.py"]}
            ],
            "classification": {
                "domain_tags": ["security"],
                "risk_level": "high",
                "refactor_depth": "atomic",
                "module_count": 1,
            },
        },
    )
    ctx, sink = _context(config, review=review, triage=triage)
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
    assert (config.artifact_dir / "routing-1.json").is_file()
    assert (config.artifact_dir / "routing-outcome-1.json").is_file()
    records, _ = events.read_events(config.artifact_dir / "events.jsonl")
    kinds = [record.kind for record in records]
    assert "routing_decision" in kinds
    assert "routing_outcome" in kinds
