"""Session setup helpers for the private review-loop runner."""

from __future__ import annotations

from typing import NamedTuple, cast

from code_review_loop import budgets, events, profiles
from code_review_loop.adapters.checks import ChecksAdapter
from code_review_loop.adapters.commit import (
    CommitAdapter,
    git_worktree_status_command_for_commit,
)
from code_review_loop.adapters.git import git_state_for_resume
from code_review_loop.adapters.phase_support import (
    log_review_findings,
    phase_timeout_seconds,
    progress_event,
    write_artifact,
)
from code_review_loop.adapters.remediation import RemediationAdapter
from code_review_loop.adapters.review import ReviewAdapter
from code_review_loop.adapters.terminal import TerminalProgressReporter
from code_review_loop.adapters.triage import TriageAdapter
from code_review_loop.artifact_ignore import ensure_default_artifact_ignore
from code_review_loop.clock import Clock, utc_iso
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import (
    PhaseHarnessBundle,
    ProcessRunner,
    ProgressReporter,
    RunContext,
)
from code_review_loop.core.review_interpretation import actionable_review_output
from code_review_loop.core.state import RunState
from code_review_loop.git_context_cache import GitContextCache
from code_review_loop.git_status import non_artifact_status_lines
from code_review_loop.identity import RunIdentity
from code_review_loop.reporting import summary_budget_payload
from code_review_loop.resume import resume_config_payload
from code_review_loop.runtime import Runner


class RunSetup(NamedTuple):
    state: RunState
    summary: dict[str, object]
    event_sink: events.JsonlSink
    ctx: RunContext
    run_id: str


def check_commit_cleanliness(config: LoopConfig, runner: Runner) -> None:
    if not config.commit_after_remediation or config.dry_run:
        return
    status_result = runner(
        git_worktree_status_command_for_commit(config),
        config.cwd,
        None,
        phase_timeout_seconds(config, config.timeout_seconds),
    )
    if status_result.returncode != 0:
        raise RuntimeError("git worktree status check failed before auto-commit could start")
    dirty_lines = non_artifact_status_lines(config, status_result.stdout)
    if dirty_lines:
        dirty_worktree = "\n".join(dirty_lines)
        raise RuntimeError(
            "refusing to enable --commit-after-remediation in a dirty worktree; "
            "clean the checkout or pass --no-commit-after-remediation.\n"
            f"Dirty paths:\n{dirty_worktree}"
        )


def archive_existing_events(config: LoopConfig) -> None:
    events_path = config.artifact_dir / events.EVENTS_FILENAME
    if not events_path.is_file():
        return
    existing_run_id = events.first_run_id(events_path)
    if existing_run_id is not None:
        events_path.rename(events_path.with_name(f"events-{existing_run_id}.jsonl"))


def create_progress_reporter(config: LoopConfig) -> ProgressReporter | None:
    if config.progress and config.progress_style in ("rich", "compact"):
        return TerminalProgressReporter(config.progress_style)
    return None


def create_run_context(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock,
    identity: RunIdentity,
    event_sink: events.JsonlSink,
    budget_state: budgets.BudgetState | None,
    phase_harnesses: PhaseHarnessBundle | None,
    terminal_ui: bool,
    git_head_at_start: str | None,
) -> RunContext:
    active_budget_state = budget_state if budget_state is not None else budgets.started_now()
    harnesses = phase_harnesses or PhaseHarnessBundle(
        checks=ChecksAdapter(config),
        commit=CommitAdapter(config),
        remediation=RemediationAdapter(config),
        review=ReviewAdapter(config),
        triage=TriageAdapter(config),
    )
    return RunContext(
        clock=clock,
        identity=identity,
        runner=cast(ProcessRunner, runner),
        event_sink=event_sink,
        budget_state=active_budget_state,
        progress_reporter=create_progress_reporter(config) if terminal_ui else None,
        phase_checks=harnesses.checks,
        phase_commit=harnesses.commit,
        phase_remediation=harnesses.remediation,
        phase_review=harnesses.review,
        phase_triage=harnesses.triage,
        git_context_cache=GitContextCache(),
        git_head_at_start=git_head_at_start,
    )


def prepare_run(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock,
    identity: RunIdentity,
    budget_state: budgets.BudgetState | None,
    phase_harnesses: PhaseHarnessBundle | None,
    terminal_ui: bool,
) -> RunSetup:
    check_commit_cleanliness(config, runner)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_artifact_ignore(config)
    run_id = identity.new_run_id()
    git_state = git_state_for_resume(config)
    git_head_value = git_state.get("head")
    git_head_at_start = git_head_value if isinstance(git_head_value, str) else None
    state = RunState.create(
        base=config.base,
        git_state=git_state,
        resume_config=resume_config_payload(config),
        run_id=run_id,
        started_at=utc_iso(clock.now()),
        profile=config.profile_name,
        max_iterations=config.max_iterations,
        artifact_dir=str(config.artifact_dir),
        commit_on_hook_failure=config.commit_on_hook_failure,
        budgets=summary_budget_payload(config),
        initial_review_file=str(config.initial_review_file) if config.initial_review_file else None,
    )
    archive_existing_events(config)
    event_sink = events.JsonlSink(config.artifact_dir, run_id, clock=clock)
    ctx = create_run_context(
        config,
        runner,
        clock=clock,
        identity=identity,
        event_sink=event_sink,
        budget_state=budget_state,
        phase_harnesses=phase_harnesses,
        terminal_ui=terminal_ui,
        git_head_at_start=git_head_at_start,
    )
    return RunSetup(state, state.to_dict(), event_sink, ctx, run_id)


def profile_routed_harnesses(profile: profiles.Profile) -> tuple[str, ...]:
    if not profile.triage.enabled or not profile.triage.routing.enabled:
        return ()
    return tuple(route.harness for route in profile.triage.routes.values())


def load_initial_review(config: LoopConfig, ctx: RunContext) -> str:
    if config.initial_review_file is None:
        return ""
    initial_review_output = actionable_review_output(config.initial_review_file.read_text(encoding="utf-8"))
    write_artifact(config.artifact_dir / "review-initial.txt", initial_review_output + "\n")
    progress_event(config, "review", "initial", "loaded", str(config.initial_review_file), ctx=ctx)
    log_review_findings(config, "initial", initial_review_output, ctx=ctx)
    return initial_review_output
