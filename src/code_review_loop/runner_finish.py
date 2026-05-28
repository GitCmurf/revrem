"""Preflight and terminal-outcome handling for the private runner."""

from __future__ import annotations

from typing import NoReturn, assert_never

from code_review_loop import artifacts, budgets, diagnostics, prompts_composer
from code_review_loop.adapters.phase_support import emit_loop_failure_event
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)
from code_review_loop.core.ports import RunContext
from code_review_loop.core.state import RunState
from code_review_loop.reporting import write_summary
from code_review_loop.runner_setup import profile_routed_harnesses
from code_review_loop.runtime import RunLoopFailed, RunnerResult


def excerpt_for_terminal(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    return prompts_composer.trim_for_prompt(text, max_chars)


def execute_stop(
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
        return RunnerResult(summary, outcome)
    if isinstance(outcome, OutcomeFailed):
        raise RunLoopFailed(summary, outcome.error, outcome=outcome) from cause
    if isinstance(outcome, (OutcomeFindings, OutcomeUnknown)):
        return RunnerResult(summary, outcome)
    assert_never(outcome)


def run_preflight(
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
    return execute_stop(
        OutcomeFailed(reason="setup_failed", error="preflight diagnostics found blocking issue"),
        state,
        summary,
        config,
        clock,
        ctx,
    )


def finish_cancelled(
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
    execute_stop(
        OutcomeFailed(reason="cancelled", error="cancelled by operator"),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )
    raise AssertionError("unreachable")


def finish_budget_exceeded(
    exc: budgets.BudgetExceeded,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> NoReturn:
    execute_stop(
        OutcomeFailed(reason="budget_ceiling_hit", error=str(exc)),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )
    raise AssertionError("unreachable")
