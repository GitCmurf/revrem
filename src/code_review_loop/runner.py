#!/usr/bin/env python3
"""Run a bounded Codex review/remediation loop against a base branch."""

from __future__ import annotations

import atexit
import json
import os
import signal
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, NamedTuple, assert_never, cast

from code_review_loop import (
    __version__ as __version__,
    artifacts,
    budgets,
    bug_bundle as bug_bundle,
    diagnostics,
    events,
    profiles,
    progress,
    prompts_composer,
)
from code_review_loop.clock import SYSTEM_CLOCK, Clock, utc_iso
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import (
    ConfigSnapshot,
    LoopAccumulator,
)
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)
from code_review_loop.core.ports import (
    CommandResult,
    PhaseHarnessBundle,
    ProcessRunner,
    ProgressReporter,
    RunContext,
)
from code_review_loop.core.review_interpretation import (
    actionable_review_output,
    extract_finding_blocks as extract_finding_blocks,
    extract_review_summary as extract_review_summary,
    review_status_diagnostics as review_status_diagnostics,
)
from code_review_loop.core.review_interpretation import (
    extract_finding_summaries as extract_finding_summaries,
)
from code_review_loop.core.state import RunState
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity
from code_review_loop.runtime import RunLoopFailed as RunLoopFailed
from code_review_loop.runtime import format_terminal_summary as format_terminal_summary
from code_review_loop.runner_shell import run_iterations as run_iterations
from code_review_loop.resume import resume_config_payload as resume_config_payload
from code_review_loop.reporting import add_artifact_paths as add_artifact_paths
from code_review_loop.reporting import add_summary_contract_fields as add_summary_contract_fields
from code_review_loop.reporting import append_run_history as append_run_history
from code_review_loop.reporting import emit_artifact_write_events as emit_artifact_write_events
from code_review_loop.reporting import iter_artifact_paths as iter_artifact_paths
from code_review_loop.reporting import summary_budget_payload as summary_budget_payload
from code_review_loop.reporting import update_unexpected_behaviors as update_unexpected_behaviors
from code_review_loop.reporting import write_summary as write_summary
from code_review_loop.adapters.phase_support import CommitFailed as CommitFailed
from code_review_loop.adapters.phase_support import _combined_output as _combined_output
from code_review_loop.adapters.phase_support import build_commit_message_command as build_commit_message_command
from code_review_loop.adapters.phase_support import compact_progress_label as compact_progress_label
from code_review_loop.adapters.phase_support import ensure_model_budget as ensure_model_budget
from code_review_loop.adapters.phase_support import emit_loop_failure_event as emit_loop_failure_event
from code_review_loop.adapters.phase_support import log_review_findings as log_review_findings
from code_review_loop.adapters.phase_support import normalize_revrem_conventional_subject as normalize_revrem_conventional_subject
from code_review_loop.adapters.phase_support import phase_timeout_seconds as phase_timeout_seconds
from code_review_loop.adapters.phase_support import print_progress_message as print_progress_message
from code_review_loop.adapters.phase_support import progress_continuation as progress_continuation
from code_review_loop.adapters.phase_support import progress_event as progress_event
from code_review_loop.adapters.phase_support import progress_log as progress_log
from code_review_loop.adapters.phase_support import progress_warning_context as progress_warning_context
from code_review_loop.adapters.phase_support import record_model_charge as record_model_charge
from code_review_loop.adapters.phase_support import remaining_wall_budget_seconds as remaining_wall_budget_seconds
from code_review_loop.adapters.phase_support import sanitize_commit_message as sanitize_commit_message
from code_review_loop.adapters.phase_support import terminal_iteration_label as terminal_iteration_label
from code_review_loop.adapters.phase_support import write_artifact as write_artifact
from code_review_loop.adapters.subprocess_runner import default_runner as default_runner
from code_review_loop.adapters.git import git_state_for_resume as git_state_for_resume
from code_review_loop.adapters.terminal import (
    restore_terminal_display as restore_terminal_display,
)
from code_review_loop.adapters.terminal import (
    terminal_title_context as terminal_title_context,
)

# REVREM-TASK-003 Wave C2a: parsers and their shared choice tuples are
# canonical in ``cli/args.py``. Runner imports them from that canonical module
# so command parsing has a single implementation.
from code_review_loop.cli import args as _cli_args

COMMIT_ON_HOOK_FAILURE_CHOICES = _cli_args.COMMIT_ON_HOOK_FAILURE_CHOICES
PROGRESS_STYLE_CHOICES = _cli_args.PROGRESS_STYLE_CHOICES
REASONING_EFFORT_CHOICES = _cli_args.REASONING_EFFORT_CHOICES
parse_args = _cli_args.parse_args
parse_bundle_bug_report_args = _cli_args.parse_bundle_bug_report_args
parse_config_args = _cli_args.parse_config_args
parse_doctor_args = _cli_args.parse_doctor_args
parse_history_args = _cli_args.parse_history_args
parse_policy_args = _cli_args.parse_policy_args
parse_replay_args = _cli_args.parse_replay_args
parse_resume_args = _cli_args.parse_resume_args
parse_suppress_args = _cli_args.parse_suppress_args
parse_triage_args = _cli_args.parse_triage_args

# REVREM-TASK-003 Wave C2a: ``LoopConfig`` assembly + argument-resolution
# helpers now live in ``cli/config_builder.py``. Runner imports the canonical
# helpers directly so the executable loop and CLI config surface share one
# implementation.
from code_review_loop.cli import config_builder as _config_builder

build_loop_config = _config_builder.build_loop_config
default_artifact_dir = _config_builder.default_artifact_dir
ensure_default_artifact_ignore = _config_builder.ensure_default_artifact_ignore
new_profile_from_args = _config_builder.new_profile_from_args
parse_harness_bin_overrides = _config_builder.parse_harness_bin_overrides
pick = _config_builder.pick
profile_from_loop_config = _config_builder.profile_from_loop_config
profile_or_default = _config_builder.profile_or_default
resolve_max_iterations = _config_builder.resolve_max_iterations
resolve_profile_timeout_seconds = _config_builder.resolve_profile_timeout_seconds
resolve_timeout_seconds = _config_builder.resolve_timeout_seconds
should_prompt_for_new_profile = _config_builder.should_prompt_for_new_profile

CANCELLATION_FORCE_WINDOW_SECONDS = 5.0
_LAST_CANCELLATION_SIGNAL_AT: float | None = None

DEFAULT_TRIAGE_PROMPT = """You are the triage step in a bounded review-remediation loop.

Read the review output and produce a concise implementation handoff for the
remediation agent. Do not edit files. Separate confirmed actionable findings,
likely false positives, implementation order, and verification commands.

Review and check output:
"""

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


@contextmanager
def terminal_recovery_context():
    global _LAST_CANCELLATION_SIGNAL_AT
    previous_handlers: dict[signal.Signals, Any] = {}
    previous_cancellation_signal_at = _LAST_CANCELLATION_SIGNAL_AT
    _LAST_CANCELLATION_SIGNAL_AT = None
    handled_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGTSTP"):
        handled_signals.append(signal.SIGTSTP)

    def handle_signal(signum: int, frame: object | None) -> None:
        restore_terminal_display()
        if signum in {signal.SIGINT, signal.SIGTERM}:
            raise cancellation_interrupt_for_signal(signum, now=time.monotonic())  # det-exempt: real-time debounce of double Ctrl-C; faking breaks the cancellation semantic
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
        if hasattr(signal, "SIGTSTP") and signum == signal.SIGTSTP:
            signal.signal(signum, handle_signal)

    for sig in handled_signals:
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, handle_signal)
    atexit.register(restore_terminal_display)
    try:
        yield
    finally:
        restore_terminal_display()
        with suppress(ValueError):
            atexit.unregister(restore_terminal_display)
        _LAST_CANCELLATION_SIGNAL_AT = previous_cancellation_signal_at
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def cancellation_interrupt_for_signal(signum: int, *, now: float) -> KeyboardInterrupt:
    global _LAST_CANCELLATION_SIGNAL_AT
    forced = (
        _LAST_CANCELLATION_SIGNAL_AT is not None
        and now - _LAST_CANCELLATION_SIGNAL_AT <= CANCELLATION_FORCE_WINDOW_SECONDS
    )
    _LAST_CANCELLATION_SIGNAL_AT = now
    signal_name = signal.Signals(signum).name
    if forced:
        return KeyboardInterrupt(f"forced cancellation after repeated {signal_name}")
    return KeyboardInterrupt(f"controlled cancellation after {signal_name}")


# Checks implementation helpers. These remain imported here only where the
# runner still has direct callers; new code should import their adapter module
# homes directly.
from code_review_loop.adapters.checks import (
    NON_PYTHON_PROJECT_MARKERS as NON_PYTHON_PROJECT_MARKERS,
)
from code_review_loop.adapters.checks import (
    PYTHON_PROJECT_MARKERS as PYTHON_PROJECT_MARKERS,
)
from code_review_loop.adapters.checks import (
    PYTHON_SCAN_SKIP_DIRS as PYTHON_SCAN_SKIP_DIRS,
)
from code_review_loop.adapters.checks import (
    has_non_python_project_surface as has_non_python_project_surface,
)
from code_review_loop.adapters.checks import (
    has_python_test_surface as has_python_test_surface,
)
from code_review_loop.adapters.checks import (
    is_pytest_command as is_pytest_command,
)
from code_review_loop.adapters.checks import (
    iter_project_files as iter_project_files,
)

# Commit-phase helpers used by the application runner while commit ownership
# continues moving behind CommitAdapter.
from code_review_loop.adapters.commit import (
    classify_commit_failure as classify_commit_failure,
)
from code_review_loop.adapters.commit import (
    commit_artifact_relative_path as commit_artifact_relative_path,
)
from code_review_loop.adapters.commit import (
    commit_command_for_message as commit_command_for_message,
)
from code_review_loop.adapters.commit import (
    commit_message_for_staged_changes as commit_message_for_staged_changes,
)
from code_review_loop.adapters.commit import (
    deterministic_commit_message as deterministic_commit_message,
)
from code_review_loop.adapters.commit import (
    format_commit_hook_failure_for_remediation as format_commit_hook_failure_for_remediation,
)
from code_review_loop.adapters.commit import (
    git_repo_root as git_repo_root,
)
from code_review_loop.adapters.commit import (
    git_worktree_status_command_for_commit as git_worktree_status_command_for_commit,
)

from code_review_loop.adapters.review import (
    review_base_hint as review_base_hint,
)
from code_review_loop.adapters.review import (
    review_base_preflight_error as review_base_preflight_error,
)
from code_review_loop.adapters.review import (
    review_failed_to_run as review_failed_to_run,
)
from code_review_loop.adapters.git import run_git_preflight as run_git_preflight

# Check failure formatting used by the application runner.


def excerpt_for_terminal(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    return prompts_composer.trim_for_prompt(text, max_chars)


def resolve_initial_review_file(value: str | None, search_root: Path) -> Path | None:
    if value is None:
        return None
    if value != "latest":
        return Path(value)

    candidates = sorted(
        (
            path
            for path in (
                search_root / "review-final.txt",
                *search_root.glob("*/review-final.txt"),
            )
            if path.is_file() and review_final_is_usable(path)
        ),
        key=lambda path: (path.stat().st_mtime, path.parent.name),
    )
    if not candidates:
        return None
    latest = candidates[-1]
    if review_final_is_resolved(latest):
        return None
    return latest


def review_final_is_resolved(review_path: Path) -> bool:
    summary_path = review_path.with_name("summary.json")
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(summary, dict) and summary.get("final_status") == "clear"


def review_final_is_usable(review_path: Path) -> bool:
    try:
        review_text = actionable_review_output(review_path.read_text(encoding="utf-8")).strip()
    except OSError:
        return False
    if not review_text:
        return False
    return not review_text.startswith("DRY_RUN")


def _config_snapshot(config: LoopConfig) -> ConfigSnapshot:
    return ConfigSnapshot(
        max_iterations=config.max_iterations,
        triage_enabled=config.triage_enabled,
        commit_after_remediation=config.commit_after_remediation,
        commit_on_hook_failure=config.commit_on_hook_failure,
        final_review=config.final_review,
    )


def _execute_stop(
    outcome: RunOutcome,
    state: RunState,
    summary: dict[str, object],
    config: LoopConfig,
    clock: Clock,
    ctx: RunContext,
    *,
    last_review_output: str = "",
    cause: BaseException | None = None,
) -> dict[str, object]:
    """Apply a Stop outcome to RunState, write summary, return or raise."""
    excerpt = (
        excerpt_for_terminal(last_review_output, config.terminal_excerpt_chars)
        if last_review_output
        else ""
    )

    def apply_common_tail(*, check_failures: bool = False) -> None:
        state.mark_outcome(outcome, excerpt=excerpt, check_failures=check_failures)
        summary.clear()
        summary.update(state.to_dict())
        write_summary(
            config,
            summary,
            clock=clock,
            budget_state=ctx.budget_state,
            event_sink=ctx.event_sink,
        )

    if isinstance(outcome, OutcomeClear):
        apply_common_tail()
        return summary

    if isinstance(outcome, OutcomeFailed):
        apply_common_tail(check_failures=outcome.check_failures)
        raise RunLoopFailed(summary, outcome.error, outcome=outcome) from cause

    if isinstance(outcome, OutcomeFindings):
        apply_common_tail(check_failures=outcome.check_failures)
        return summary

    if isinstance(outcome, OutcomeUnknown):
        apply_common_tail(check_failures=outcome.check_failures)
        return summary

    assert_never(outcome)


def run_loop(
    config: LoopConfig,
    runner: Runner = default_runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> dict[str, object]:
    if not terminal_ui:
        return _run_session(
            config,
            runner,
            clock=clock,
            identity=identity,
            budget_state=budget_state,
            phase_harnesses=phase_harnesses,
            terminal_ui=False,
        )
    with (
        terminal_recovery_context(),
        terminal_title_context(config),
        progress_warning_context(),
        progress.rich_live_progress(config.progress and config.progress_style == "rich"),
    ):
        return _run_session(
            config,
            runner,
            clock=clock,
            identity=identity,
            budget_state=budget_state,
            phase_harnesses=phase_harnesses,
            terminal_ui=True,
        )


def resume_run(run_dir: Path) -> dict[str, object]:
    from code_review_loop import resume

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("summary.json must contain a JSON object")
    budget_issues = resume.resume_budget_ceiling_issues(summary)
    if budget_issues:
        raise ValueError("; ".join(issue.message for issue in budget_issues))
    config, resumed_budget_state = resume.resume_loop_config(summary, run_dir=run_dir)
    return run_loop(config, budget_state=resumed_budget_state)


class _RunSetup(NamedTuple):
    state: RunState
    summary: dict[str, object]
    event_sink: events.JsonlSink
    ctx: RunContext
    run_id: str


class _IterationRun(NamedTuple):
    acc: LoopAccumulator
    pending_check_failures: str
    result: dict[str, object] | None


def _check_commit_cleanliness(config: LoopConfig, runner: Runner) -> None:
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
    dirty_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    if dirty_lines:
        dirty_worktree = "\n".join(dirty_lines)
        raise RuntimeError(
            "refusing to enable --commit-after-remediation in a dirty worktree; "
            "clean the checkout or pass --no-commit-after-remediation.\n"
            f"Dirty paths:\n{dirty_worktree}"
        )


def _archive_existing_events(config: LoopConfig) -> None:
    events_path = config.artifact_dir / events.EVENTS_FILENAME
    if not events_path.is_file():
        return
    existing_run_id = events.first_run_id(events_path)
    if existing_run_id is not None:
        events_path.rename(events_path.with_name(f"events-{existing_run_id}.jsonl"))


def _create_progress_reporter(config: LoopConfig) -> ProgressReporter | None:
    from code_review_loop.adapters.terminal import TerminalProgressReporter

    if config.progress and config.progress_style in ("rich", "compact"):
        return TerminalProgressReporter(config.progress_style)
    return None


def _create_run_context(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock,
    identity: RunIdentity,
    event_sink: events.JsonlSink,
    budget_state: budgets.BudgetState | None,
    phase_harnesses: PhaseHarnessBundle | None,
    terminal_ui: bool,
) -> RunContext:
    from code_review_loop.adapters.checks import ChecksAdapter
    from code_review_loop.adapters.commit import CommitAdapter
    from code_review_loop.adapters.remediation import RemediationAdapter
    from code_review_loop.adapters.review import ReviewAdapter
    from code_review_loop.adapters.triage import TriageAdapter

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
        progress_reporter=_create_progress_reporter(config) if terminal_ui else None,
        phase_checks=harnesses.checks,
        phase_commit=harnesses.commit,
        phase_remediation=harnesses.remediation,
        phase_review=harnesses.review,
        phase_triage=harnesses.triage,
    )


def _prepare_run(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock,
    identity: RunIdentity,
    budget_state: budgets.BudgetState | None,
    phase_harnesses: PhaseHarnessBundle | None,
    terminal_ui: bool,
) -> _RunSetup:
    _check_commit_cleanliness(config, runner)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_artifact_ignore(config)
    run_id = identity.new_run_id()
    state = RunState.create(
        base=config.base,
        git_state=git_state_for_resume(config),
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
    _archive_existing_events(config)
    event_sink = events.JsonlSink(config.artifact_dir, run_id, clock=clock)
    ctx = _create_run_context(
        config,
        runner,
        clock=clock,
        identity=identity,
        event_sink=event_sink,
        budget_state=budget_state,
        phase_harnesses=phase_harnesses,
        terminal_ui=terminal_ui,
    )
    return _RunSetup(state, state.to_dict(), event_sink, ctx, run_id)


def _profile_routed_harnesses(profile: profiles.Profile) -> tuple[str, ...]:
    if not profile.triage.enabled or not profile.triage.routing.enabled:
        return ()
    return tuple(route.harness for route in profile.triage.routes.values())


def _run_preflight(
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    *,
    clock: Clock,
    ctx: RunContext,
) -> dict[str, object] | None:
    if not config.preflight_enabled or config.dry_run:
        return None
    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=config.cwd,
            base=config.base,
            artifact_dir=config.artifact_dir,
            artifact_dir_is_default=config.artifact_dir_is_default,
            codex_bin=config.codex_bin,
            review_harness=config.review_harness,
            remediation_harness=config.remediation_harness,
            triage_enabled=config.triage_enabled,
            triage_harness=config.triage_harness,
            commit_message_harness=config.commit_message_harness,
            routed_harnesses=(
                _profile_routed_harnesses(config.profile_v2)
                if config.profile_v2 is not None
                else ()
            ),
            harness_executables=config.harness_executables,
            check_commands=config.check_commands,
            commit_after_remediation=config.commit_after_remediation,
            timeout_seconds=config.timeout_seconds,
            review_timeout_seconds=config.review_timeout_seconds,
            remediation_timeout_seconds=config.remediation_timeout_seconds,
            triage_timeout_seconds=config.triage_timeout_seconds,
        )
    )
    if not diagnostics.has_blocking_issue(issues):
        return None
    artifacts.write_json_artifact(
        config.artifact_dir,
        "diagnostics.json",
        diagnostics.doctor_payload(issues),
    )
    emit_loop_failure_event(
        config,
        phase="preflight",
        iteration=None,
        reason="setup_failed",
        error="preflight diagnostics found blocking issue",
        ctx=ctx,
    )
    return _execute_stop(
        OutcomeFailed(reason="setup_failed", error="preflight diagnostics found blocking issue"),
        state, summary, config, clock, ctx,
    )


def _load_initial_review(config: LoopConfig, ctx: RunContext) -> str:
    if config.initial_review_file is None:
        return ""
    initial_review_output = actionable_review_output(config.initial_review_file.read_text(encoding="utf-8"))
    write_artifact(config.artifact_dir / "review-initial.txt", initial_review_output + "\n")
    progress_event(config, "review", "initial", "loaded", str(config.initial_review_file), ctx=ctx)
    log_review_findings(config, "initial", initial_review_output, ctx=ctx)
    return initial_review_output


def _finish_cancelled(
    exc: KeyboardInterrupt,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> dict[str, object]:
    artifacts.write_json_artifact(
        config.artifact_dir,
        "diagnostics.json",
        diagnostics.doctor_payload(
            [
                diagnostics.DiagnosticIssue(
                    code="revrem.run.cancelled",
                    severity="blocking",
                    message="RevRem run was cancelled by the operator.",
                    hint="Inspect summary.json and events.jsonl to determine the last completed phase before resuming or rerunning.",
                    evidence={"reason": "operator_interrupt"},
                )
            ]
        ),
    )
    if ctx.event_sink is not None:
        ctx.event_sink.emit(
            "cancellation",
            phase="run",
            payload={
                "reason": "operator_interrupt",
                "message": "cancelled by operator",
            },
        )
    return _execute_stop(
        OutcomeFailed(reason="cancelled", error="cancelled by operator"),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )


def _finish_budget_exceeded(
    exc: budgets.BudgetExceeded,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> dict[str, object]:
    return _execute_stop(
        OutcomeFailed(reason="budget_ceiling_hit", error=str(exc)),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )


def _run_session_body(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    run_id: str,
) -> dict[str, object]:
    preflight_result = _run_preflight(config, state, summary, clock=clock, ctx=ctx)
    if preflight_result is not None:
        return preflight_result

    initial_review_output = _load_initial_review(config, ctx)
    snap = _config_snapshot(config)
    shell_result = run_iterations(
        config=config,
        state=state,
        clock=clock,
        ctx=ctx,
        snap=snap,
        initial_review_output=initial_review_output,
        run_id=run_id,
    )
    return _execute_stop(
        shell_result.outcome,
        state,
        summary,
        config,
        clock,
        ctx,
        cause=shell_result.cause,
        last_review_output=shell_result.last_review_output,
    )


def _run_session(
    config: LoopConfig,
    runner: Runner = default_runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> dict[str, object]:
    if config.max_iterations < 1:
        raise ValueError("--max-iterations must be at least 1")

    setup = _prepare_run(
        config,
        runner,
        clock=clock,
        identity=identity,
        budget_state=budget_state,
        phase_harnesses=phase_harnesses,
        terminal_ui=terminal_ui,
    )
    state = setup.state
    summary = setup.summary

    event_sink = setup.event_sink
    ctx = setup.ctx
    run_id = setup.run_id
    try:
        return _run_session_body(
            config=config,
            state=state,
            summary=summary,
            clock=clock,
            ctx=ctx,
            run_id=run_id,
        )
    except KeyboardInterrupt as exc:
        return _finish_cancelled(exc, config=config, state=state, summary=summary, clock=clock, ctx=ctx)
    except budgets.BudgetExceeded as exc:
        return _finish_budget_exceeded(exc, config=config, state=state, summary=summary, clock=clock, ctx=ctx)
    finally:
        event_sink.close()
