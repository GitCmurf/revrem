#!/usr/bin/env python3
"""Run a bounded Codex review/remediation loop against a base branch."""

from __future__ import annotations

import atexit
import json
import os
import signal
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, NoReturn, assert_never

from code_review_loop import (
    __version__ as __version__,
    artifacts,
    budgets,
    bug_bundle as bug_bundle,
    diagnostics,
    progress,
    prompts_composer,
)
from code_review_loop.clock import SYSTEM_CLOCK, Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import (
    ConfigSnapshot,
)
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)
from code_review_loop.core.ports import (
    PhaseHarnessBundle,
    RunContext,
)
from code_review_loop.core.review_interpretation import (
    extract_finding_blocks as extract_finding_blocks,
    extract_review_summary as extract_review_summary,
    review_status_diagnostics as review_status_diagnostics,
)
from code_review_loop.core.review_interpretation import (
    extract_finding_summaries as extract_finding_summaries,
)
from code_review_loop.core.state import RunState
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity
from code_review_loop.runtime import RunnerResult as RunnerResult
from code_review_loop.runtime import RunLoopFailed as RunLoopFailed
from code_review_loop.runtime import Runner as Runner
from code_review_loop.runtime import format_terminal_summary as format_terminal_summary
from code_review_loop.runner_setup import load_initial_review as load_initial_review
from code_review_loop.runner_setup import prepare_run as prepare_run
from code_review_loop.runner_setup import profile_routed_harnesses as profile_routed_harnesses
from code_review_loop.runner_shell import run_iterations as run_iterations
from code_review_loop.reporting import add_artifact_paths as add_artifact_paths
from code_review_loop.reporting import add_summary_contract_fields as add_summary_contract_fields
from code_review_loop.reporting import append_run_history as append_run_history
from code_review_loop.reporting import emit_artifact_write_events as emit_artifact_write_events
from code_review_loop.reporting import iter_artifact_paths as iter_artifact_paths
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
from code_review_loop.adapters.terminal import (
    restore_terminal_display as restore_terminal_display,
)
from code_review_loop.adapters.terminal import (
    terminal_title_context as terminal_title_context,
)

CANCELLATION_FORCE_WINDOW_SECONDS = 5.0
_LAST_CANCELLATION_SIGNAL_AT: float | None = None

DEFAULT_TRIAGE_PROMPT = """You are the triage step in a bounded review-remediation loop.

Read the review output and produce a concise implementation handoff for the
remediation agent. Do not edit files. Separate confirmed actionable findings,
likely false positives, implementation order, and verification commands.

Review and check output:
"""

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
) -> RunnerResult:
    """Apply a Stop outcome to RunState, write summary, return or raise."""
    excerpt = (
        excerpt_for_terminal(last_review_output, config.terminal_excerpt_chars)
        if last_review_output
        else ""
    )

    def apply_common_tail() -> None:
        state.mark_outcome(outcome, excerpt=excerpt)
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
        return RunnerResult(summary, outcome)

    if isinstance(outcome, OutcomeFailed):
        apply_common_tail()
        raise RunLoopFailed(summary, outcome.error, outcome=outcome) from cause

    if isinstance(outcome, OutcomeFindings):
        apply_common_tail()
        return RunnerResult(summary, outcome)

    if isinstance(outcome, OutcomeUnknown):
        apply_common_tail()
        return RunnerResult(summary, outcome)

    assert_never(outcome)


def run_loop(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> RunnerResult:
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


def resume_run(run_dir: Path, runner: Runner) -> RunnerResult:
    from code_review_loop import resume

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("summary.json must contain a JSON object")
    budget_issues = resume.resume_budget_ceiling_issues(summary)
    if budget_issues:
        raise ValueError("; ".join(issue.message for issue in budget_issues))
    config, resumed_budget_state = resume.resume_loop_config(summary, run_dir=run_dir)
    return run_loop(config, runner, budget_state=resumed_budget_state)


def _run_preflight(
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    *,
    clock: Clock,
    ctx: RunContext,
) -> RunnerResult | None:
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
                profile_routed_harnesses(config.profile_v2)
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


def _finish_cancelled(
    exc: KeyboardInterrupt,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> NoReturn:
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
    _execute_stop(
        OutcomeFailed(reason="cancelled", error="cancelled by operator"),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )
    raise AssertionError("unreachable")


def _finish_budget_exceeded(
    exc: budgets.BudgetExceeded,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> NoReturn:
    _execute_stop(
        OutcomeFailed(reason="budget_ceiling_hit", error=str(exc)),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )
    raise AssertionError("unreachable")


def _run_session_body(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    run_id: str,
) -> RunnerResult:
    preflight_result = _run_preflight(config, state, summary, clock=clock, ctx=ctx)
    if preflight_result is not None:
        return preflight_result

    initial_review_output = load_initial_review(config, ctx)
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
    runner: Runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> RunnerResult:
    if config.max_iterations < 1:
        raise ValueError("--max-iterations must be at least 1")

    setup = prepare_run(
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
