from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from code_review_loop import budgets, events, profiles
from code_review_loop.adapters.phase_support import CommitFailed
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import ConfigSnapshot, EngineState, LoopAccumulator, LoopStarted
from code_review_loop.core.ports import (
    CommandResult,
    CommitOutcome,
    CommitRequest,
    RemediationOutcome,
    RemediationRequest,
    RunContext,
)
from code_review_loop.core.state import RunState
from code_review_loop.runner_commit_phase import execute_commit_phase
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
        initial_review_mode=config.initial_review_mode,
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


class StaticRemediationHarness:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[RemediationRequest] = []

    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        self.calls.append(request)
        return RemediationOutcome(result=CommandResult(["fake", "exec"], 0, stdout=self.stdout))


class SequencedGitStatusRunner:
    def __init__(self, statuses: list[str], validation_stdout: str | None = None) -> None:
        self.statuses = statuses
        self.validation_stdout = validation_stdout or _stale_validation_output("resolved")
        self.calls: list[list[str]] = []

    def __call__(self, args, cwd, input_text=None, timeout_seconds=None):
        command = list(args)
        self.calls.append(command)
        if len(command) > 1 and command[1] == "exec":
            return CommandResult(command, 0, stdout=self.validation_stdout)
        if command == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
            if not self.statuses:
                raise AssertionError("git status sequence exhausted")
            return CommandResult(command, 0, stdout=self.statuses.pop(0))
        return CommandResult(command, 0, stdout="")


def _stale_validation_output(status: str) -> str:
    return (
        "Preface should not be surfaced.\n"
        "STALE_REVIEW_VALIDATION:\n"
        f"status: {status}\n"
        "findings_checked: 1\n"
        "evidence:\n"
        f"- stale finding is {status}\n"
        f"REVREM_STALE_REVIEW_STATUS: {status}\n"
        "[stderr]\n"
        "provider footer should not be surfaced\n"
    )


def _stale_validation_runner(status: str = "resolved") -> RecordingProcessRunner:
    return RecordingProcessRunner(
        {"exec": CommandResult(["codex", "exec"], 0, stdout=_stale_validation_output(status))}
    )


def _stale_validation_runner_with_stderr_echo(
    status: str,
    *,
    echoed_status: str,
) -> RecordingProcessRunner:
    return RecordingProcessRunner(
        {
            "exec": CommandResult(
                ["codex", "exec"],
                0,
                stdout=_stale_validation_output(status),
                stderr=f"Prompt template: REVREM_STALE_REVIEW_STATUS: {echoed_status}\n",
            )
        }
    )


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


def test_commit_phase_refreshes_expected_head_without_cwd_git_marker(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    subdir = repo / "subdir"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()
    config = replace(_config(subdir), commit_after_remediation=True)
    process_runner = RecordingProcessRunner(
        {
            "rev-parse": CommandResult(["git", "rev-parse", "HEAD"], 0, stdout="new-head\n"),
        }
    )
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        commit=StaticCommitHarness(status="committed"),
        runner=process_runner,
    )
    try:
        result = execute_commit_phase(
            config=config,
            ctx=ctx,
            iterations=[{"iteration": 1}],
            engine_state=EngineState(
                cfg=_snapshot(config),
                acc=LoopAccumulator(pending_check_failures=""),
                event=LoopStarted(),
                iteration=1,
            ),
            expected_head="old-head",
        )
    finally:
        sink.close()

    assert result.expected_head == "new-head"


def test_runner_shell_marks_stale_review_resolved_when_validation_noops(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness(
        "Preface should not be surfaced.\n"
        "STALE_REVIEW_VALIDATION:\n"
        "status: resolved\n"
        "findings_checked: 1\n"
        "evidence:\n"
        "- git diff --check passed\n"
        "REVREM_STALE_REVIEW_STATUS: resolved\n"
        "[stderr]\n"
        "provider footer should not be surfaced\n"
    )
    commit = StaticCommitHarness(status="skipped_no_changes")
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        commit=commit,
        runner=_stale_validation_runner("resolved"),
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "stale_review_already_resolved"
    assert result.outcome.__class__.__name__ == "OutcomeClear"
    assert result.last_review_output.startswith("STALE_REVIEW_VALIDATION:")
    assert "Preface should not be surfaced" not in result.last_review_output
    assert "provider footer should not be surfaced" not in result.last_review_output
    assert remediation.calls == []
    assert state.iterations[0]["stale_review_resolved"] is True
    assert (config.artifact_dir / "stale-validation-1.txt").is_file()
    assert (config.artifact_dir / "stale-validation-1-prompt.txt").is_file()


def test_runner_shell_skips_commit_when_stale_review_resolved(
    tmp_path: Path,
) -> None:
    """When stale-review validation resolves an issue, the loop must stop
    with ``stale_review_already_resolved`` before the commit phase is reached.
    Calling the commit adapter after the stale finding is resolved would be
    a redundant provider call and could mask the resolved state with a
    generic ``review_clear`` from a final review.
    """
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness(
        "STALE_REVIEW_VALIDATION:\n"
        "status: resolved\n"
        "findings_checked: 1\n"
        "evidence:\n"
        "- tests passed\n"
        "REVREM_STALE_REVIEW_STATUS: resolved\n"
    )
    commit = StaticCommitHarness(status="committed")
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["findings", "clear"]),
        remediation=remediation,
        commit=commit,
        runner=_stale_validation_runner("resolved"),
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "stale_review_already_resolved"
    assert result.outcome.__class__.__name__ == "OutcomeClear"
    assert remediation.calls == []
    assert commit.calls == [], (
        "commit phase must not run after stale-review validation resolved "
        "the finding; the loop should stop at the checks phase"
    )


def test_runner_shell_stale_review_resolved_without_commit_exits_clear(
    tmp_path: Path,
) -> None:
    """In non-commit mode the loop must stop with ``stale_review_already_resolved``
    once stale-review validation emits the resolved marker. The previous
    behaviour fell through to the next review action, which made
    ``--no-final-review`` runs end at ``max_iterations_reached`` and
    final-review runs issue a redundant provider call.
    """
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=False,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness(
        "STALE_REVIEW_VALIDATION:\n"
        "status: resolved\n"
        "findings_checked: 1\n"
        "evidence:\n"
        "- git diff --check passed\n"
        "REVREM_STALE_REVIEW_STATUS: resolved\n"
    )
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        runner=_stale_validation_runner("resolved"),
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "stale_review_already_resolved"
    assert result.outcome.__class__.__name__ == "OutcomeClear"
    assert remediation.calls == []
    assert state.iterations[0]["stale_review_resolved"] is True


def test_runner_shell_stale_review_resolved_fails_if_remediation_edits(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=False,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness(
        "STALE_REVIEW_VALIDATION:\n"
        "status: resolved\n"
        "findings_checked: 1\n"
        "evidence:\n"
        "- old finding is gone\n"
        "REVREM_STALE_REVIEW_STATUS: resolved\n"
    )
    runner = SequencedGitStatusRunner(["", " M src/changed.py\0"])
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        runner=runner,
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.__class__.__name__ == "OutcomeFailed"
    assert result.outcome.reason == "stale_validation_failed"
    assert "changed non-artifact git status" in result.outcome.error
    assert "M src/changed.py" in result.outcome.error


def test_runner_shell_stale_review_resolved_fails_if_checks_leave_edits(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=False,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness(
        "STALE_REVIEW_VALIDATION:\n"
        "status: resolved\n"
        "findings_checked: 1\n"
        "evidence:\n"
        "- old finding is gone\n"
        "REVREM_STALE_REVIEW_STATUS: resolved\n"
    )
    runner = SequencedGitStatusRunner(["", "", "?? leaked.txt\0"])
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        runner=runner,
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.__class__.__name__ == "OutcomeFailed"
    assert result.outcome.reason == "remediation_failed"
    assert "changed non-artifact git status" in result.outcome.error
    assert "?? leaked.txt" in result.outcome.error


def test_runner_shell_keeps_no_change_findings_without_stale_marker(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness("No edits were needed.\n")
    commit = StaticCommitHarness(status="skipped_no_changes")
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        commit=commit,
        runner=_stale_validation_runner("still_applies"),
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "no_changes_after_remediation"
    assert result.outcome.__class__.__name__ == "OutcomeFindings"
    assert remediation.calls
    assert state.iterations[0]["stale_review_still_applies"] is True
    assert "Old finding" in result.last_review_output


def test_runner_shell_stale_review_still_applies_ignores_stderr_resolved_echo(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness("No edits were needed.\n")
    commit = StaticCommitHarness(status="skipped_no_changes")
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        commit=commit,
        runner=_stale_validation_runner_with_stderr_echo(
            "still_applies",
            echoed_status="resolved",
        ),
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.reason == "no_changes_after_remediation"
    assert result.outcome.__class__.__name__ == "OutcomeFindings"
    assert remediation.calls
    assert state.iterations[0]["stale_review_still_applies"] is True


def test_runner_shell_stale_review_unknown_stops_before_remediation(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path, max_iterations=1, triage_enabled=False),
        commit_after_remediation=True,
        initial_review_mode="stale",
    )
    remediation = StaticRemediationHarness("should not run\n")
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["clear"]),
        remediation=remediation,
        runner=_stale_validation_runner("unknown"),
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
            initial_review_output="Full review comments:\n\n- [P2] Old finding\n",
            run_id=FIXED_RUN_ID,
        )
    finally:
        sink.close()

    assert result.outcome.__class__.__name__ == "OutcomeFailed"
    assert result.outcome.reason == "stale_validation_failed"
    assert remediation.calls == []


def test_runner_shell_ignores_stale_resolved_marker_outside_validation_mode(
    tmp_path: Path,
) -> None:
    """A normal remediation may quote the stale-review marker while fixing a
    stale-review-related bug. Only actual stale-validation runs should let that
    marker change the loop outcome or commit invariant.
    """
    config = replace(
        _config(tmp_path, max_iterations=2, triage_enabled=False),
        commit_after_remediation=True,
        initial_review_mode="none",
    )
    remediation = StaticRemediationHarness(
        "Fixed the stale-review handling bug.\n"
        "The prompt referenced REVREM_STALE_REVIEW_STATUS: resolved as text.\n"
    )
    commit = StaticCommitHarness(status="committed")
    ctx, sink = _context(
        config,
        review=SequencedReviewHarness(["findings", "clear"]),
        remediation=remediation,
        commit=commit,
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

    assert result.outcome.reason == "review_clear"
    assert result.outcome.__class__.__name__ == "OutcomeClear"
    assert commit.calls, "normal commit flow must continue outside stale validation"
    assert "stale_review_resolved" not in state.iterations[0]


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
