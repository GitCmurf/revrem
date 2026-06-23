#!/usr/bin/env python3
"""Run a bounded Codex review/remediation loop against a base branch."""

from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import (
    budgets,
    progress,
)
from code_review_loop.clock import SYSTEM_CLOCK, Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import (
    ConfigSnapshot,
)
from code_review_loop.core.ports import PhaseHarnessBundle, RunContext
from code_review_loop.core.state import RunState
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity
from code_review_loop.runtime import Runner
from code_review_loop.runtime import RunnerResult
from code_review_loop.runner_finish import execute_stop
from code_review_loop.runner_finish import finish_budget_exceeded
from code_review_loop.runner_finish import finish_cancelled
from code_review_loop.runner_finish import run_preflight
from code_review_loop.runner_setup import load_initial_review
from code_review_loop.runner_setup import prepare_run
from code_review_loop.runner_shell import run_iterations
from code_review_loop.adapters.phase_support import progress_warning_context
from code_review_loop.adapters.terminal import (
    terminal_title_context,
)
from code_review_loop.adapters.terminal import terminal_recovery_context

DEFAULT_TRIAGE_PROMPT = """You are the triage step in a bounded review-remediation loop.

Read the review output and produce a concise implementation handoff for the
remediation agent. Do not edit files. Separate confirmed actionable findings,
likely false positives, implementation order, and verification commands.

Review and check output:
"""


def _config_snapshot(config: LoopConfig) -> ConfigSnapshot:
    return ConfigSnapshot(
        max_iterations=config.max_iterations,
        triage_enabled=config.triage_enabled,
        commit_after_remediation=config.commit_after_remediation,
        commit_on_hook_failure=config.commit_on_hook_failure,
        final_review=config.final_review,
        inner_check_retries=config.inner_check_retries,
    )


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
        progress.rich_live_progress(
            config.progress and config.progress_style == "rich",
            no_tty=config.no_tty,
        ),
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


def _run_session_body(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    run_id: str,
) -> RunnerResult:
    preflight_result = run_preflight(config, state, summary, clock=clock, ctx=ctx)
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
    return execute_stop(
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
        return finish_cancelled(
            exc, config=config, state=state, summary=summary, clock=clock, ctx=ctx
        )
    except budgets.BudgetExceeded as exc:
        return finish_budget_exceeded(
            exc, config=config, state=state, summary=summary, clock=clock, ctx=ctx
        )
    finally:
        event_sink.close()
