"""Private imperative shell that executes core engine actions."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, replace
from typing import Literal, cast

from code_review_loop import budgets, stale_review, stale_validation_status, triage
from code_review_loop.adapters.checks import (
    all_failed_checks_are_revrem_timeouts as _all_failed_checks_are_revrem_timeouts,
)
from code_review_loop.adapters.checks import format_check_failures as _format_check_failures
from code_review_loop.adapters.commit import format_commit_hook_failure_for_remediation
from code_review_loop.adapters.phase_support import (
    CommitFailed,
    _combined_output,
    emit_loop_failure_event,
    progress_event,
)
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import (
    Action,
    ChecksDone,
    CommitDone,
    ConfigSnapshot,
    Continue,
    EngineState,
    LoopAccumulator,
    LoopStarted,
    RemediationDone,
    RetryViaChecks,
    RetryViaCommitHook,
    ReviewDone,
    RunChecks,
    RunCommit,
    RunRemediation,
    RunReview,
    RunTriage,
    TriageDone,
)
from code_review_loop.core.engine import run as run_engine
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)
from code_review_loop.core.ports import (
    ChecksRequest,
    RemediationRequest,
    ReviewRequest,
    RunContext,
    TriageRequest,
)
from code_review_loop.core.review_interpretation import (
    actionable_review_output,
    detect_review_status,
)
from code_review_loop.core.state import RunState
from code_review_loop.iteration_labels import artifact_label, event_iteration_label
from code_review_loop.routing_artifacts import record_routing_outcome
from code_review_loop.run_guards import assert_worktree_stable_before_remediation
from code_review_loop.runner_commit_phase import execute_commit_phase
from code_review_loop.runner_routing_phase import resolve_routing_accumulator

_ENGINE_STEPS_PER_ITERATION = 10
_ENGINE_STEP_BUDGET_OVERHEAD = 4


class _RunnerEngineExecutor:
    def __init__(
        self,
        *,
        config: LoopConfig,
        state: RunState,
        clock: Clock,
        ctx: RunContext,
        run_id: str,
        initial_review_output: str,
    ) -> None:
        self.config = config
        self.state = state
        self.clock = clock
        self.ctx = ctx
        self.run_id = run_id
        self.initial_review_output = initial_review_output
        self.cause: BaseException | None = None
        self.routing_context_cache: triage.RoutingContextCache = {}
        self.latest_state: EngineState | None = None
        self.expected_head = ctx.git_head_at_start
        self.stale_review_validation_output = ""
        self.stale_review_status_before: tuple[str, ...] | None = None

    def execute(self, action: Action, engine_state: EngineState) -> EngineState:
        match action:
            case Continue():
                next_state = replace(engine_state, event=LoopStarted(), iteration=engine_state.iteration + 1)
            case RunReview(is_final=is_final):
                next_state = self._run_review(engine_state, is_final=is_final)
            case RunTriage():
                next_state = self._run_triage(engine_state)
            case RunRemediation():
                next_state = self._run_remediation(engine_state)
            case RunChecks():
                next_state = self._run_checks(engine_state)
            case RunCommit():
                next_state = self._run_commit(engine_state)
            case RetryViaCommitHook():
                next_state = self._retry_after_commit_hook(engine_state, action)
            case RetryViaChecks():
                next_state = self._retry_after_checks(engine_state)
            case _:
                raise AssertionError(f"engine executor received terminal action: {action!r}")
        self.latest_state = next_state
        return next_state

    def _run_review(self, engine_state: EngineState, *, is_final: bool) -> EngineState:
        if is_final:
            try:
                outcome = self.ctx.phase_review.execute(
                    ReviewRequest(artifact_label="review-final", display_label="final"),
                    self.ctx,
                )
            except RuntimeError as exc:
                self.cause = exc
                self.state.iterations.append({"iteration": "final", "review_failed": True})
                return replace(
                    engine_state,
                    event=ReviewDone(is_final=True, status="unknown", exc=exc),
                )
            status, review = outcome.status, outcome.result
            acc = replace(
                engine_state.acc,
                last_review_output=actionable_review_output(_combined_output(review)),
                last_review_status=status,
            )
            if status == "unknown" and not acc.pending_check_failures:
                self.state.iterations.append({"iteration": "final", "review_status": status})
            return replace(engine_state, acc=acc, event=ReviewDone(is_final=True, status=status))

        iteration = engine_state.iteration
        acc = replace(
            engine_state.acc,
            resolved_route=None,
            remediation_result_returncode=None,
            remediation_duration=0.0,
            inner_check_retry_count=0,
            stale_review_resolved=False,
            stale_review_dirty="",
        )
        self.stale_review_status_before = None
        if iteration == 1 and self.initial_review_output:
            status = cast("Literal['clear', 'findings', 'unknown']", detect_review_status(self.initial_review_output))
            if status == "unknown":
                status = "findings"
            self.state.iterations.append(
                {
                    "iteration": iteration,
                    "review_status": status,
                    "review_source": str(self.config.initial_review_file),
                }
            )
            acc = replace(
                acc,
                last_review_output=self.initial_review_output,
                last_review_status=cast("Literal['clear', 'findings', 'unknown']", status),
            )
            return replace(engine_state, acc=acc, event=ReviewDone(is_final=False, status=acc.last_review_status))

        try:
            outcome = self.ctx.phase_review.execute(
                ReviewRequest(artifact_label=f"review-{iteration}", display_label=str(iteration)),
                self.ctx,
            )
            status, review = outcome.status, outcome.result
        except RuntimeError as exc:
            self.cause = exc
            self.state.iterations.append({"iteration": iteration, "review_failed": True})
            emit_loop_failure_event(
                self.config,
                phase="review",
                iteration=iteration,
                reason="review_failed",
                error=str(exc),
                ctx=self.ctx,
            )
            return replace(
                engine_state,
                event=ReviewDone(is_final=False, status="unknown", exc=exc),
            )
        review_output = actionable_review_output(_combined_output(review))
        self.state.iterations.append({"iteration": iteration, "review_status": status})
        acc = replace(acc, last_review_output=review_output, last_review_status=status)
        return replace(engine_state, acc=acc, event=ReviewDone(is_final=False, status=status))

    def _run_triage(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        remediation_input = engine_state.acc.last_review_output
        if engine_state.acc.pending_check_failures:
            remediation_input = engine_state.acc.pending_check_failures + "\n\n" + remediation_input
        try:
            source_review_artifact = "review-initial.txt" if iteration == 1 and self.initial_review_output else f"review-{iteration}.txt"
            triage_outcome = self.ctx.phase_triage.execute(
                TriageRequest(
                    iteration=iteration,
                    run_id=self.run_id,
                    source_review_artifact=source_review_artifact,
                    review_output=remediation_input,
                ),
                self.ctx,
            )
            acc = replace(engine_state.acc, remediation_input=triage_outcome.handoff)
            suppressed_count = triage_outcome.suppressed_count
            triage_no_actionable = triage_outcome.is_clear
            triage_payload = triage_outcome.payload
            if suppressed_count:
                self.state.iterations[-1]["suppressed_findings_count"] = suppressed_count
            if triage_no_actionable:
                if suppressed_count:
                    self.state.iterations[-1]["suppressed_findings"] = True
                    self.state.set_suppressed_findings_count(suppressed_count)
                if engine_state.acc.pending_check_failures:
                    acc = replace(acc, remediation_input=engine_state.acc.pending_check_failures)
                return replace(
                    engine_state,
                    acc=acc,
                    event=TriageDone(is_clear=True, suppressed_count=suppressed_count),
                )

            if triage_payload and self.config.triage_contract == "v2" and self.config.profile_v2:
                acc = resolve_routing_accumulator(
                    config=self.config,
                    ctx=self.ctx,
                    run_id=self.run_id,
                    iteration=iteration,
                    triage_payload=triage_payload,
                    acc=acc,
                    cache=self.routing_context_cache,
                )
        except budgets.BudgetExceeded:
            raise
        except Exception as exc:
            self.cause = exc
            self.state.iterations[-1]["triage_failed"] = True
            emit_loop_failure_event(
                self.config,
                phase="triage",
                iteration=iteration,
                reason="triage_failed",
                error=str(exc),
                ctx=self.ctx,
            )
            return replace(engine_state, event=TriageDone(is_clear=False, exc=exc))
        return replace(engine_state, acc=acc, event=TriageDone(is_clear=False))

    def _run_remediation(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        retry_count = engine_state.acc.inner_check_retry_count
        artifact_stem = artifact_label(iteration, retry_count)
        display_label = event_iteration_label(iteration, retry_count)
        remediation_input = engine_state.acc.remediation_input
        if not self.config.triage_enabled:
            remediation_input = engine_state.acc.last_review_output
            if engine_state.acc.pending_check_failures:
                remediation_input = engine_state.acc.pending_check_failures + "\n\n" + remediation_input
        validating_stale_review = stale_review.should_validate_stale_review(
            self.config,
            engine_state,
            initial_review_output=self.initial_review_output,
        )
        if validating_stale_review:
            self.stale_review_status_before = stale_validation_status.non_artifact_status_snapshot(
                self.config,
                self.ctx,
            )
            remediation_input = stale_review.validation_prompt(remediation_input)
        try:
            assert_worktree_stable_before_remediation(
                self.config,
                self.ctx,
                engine_state,
                expected_head=self.expected_head,
            )
            rem_start_time = self.clock.monotonic()
            rem_outcome = self.ctx.phase_remediation.execute(
                RemediationRequest(
                    iteration=iteration,
                    remediation_input=remediation_input,
                    resolved_route=engine_state.acc.resolved_route,
                    artifact_label=f"remediation-{artifact_stem}",
                    display_label=display_label,
                ),
                self.ctx,
            )
            combined_output = _combined_output(rem_outcome.result)
            acc = replace(
                engine_state.acc,
                remediation_input=remediation_input,
                remediation_result_returncode=rem_outcome.result.returncode,
                remediation_duration=self.clock.monotonic() - rem_start_time,
                stale_review_resolved=(
                    validating_stale_review
                    and stale_review.contains_resolved_marker(combined_output)
                ),
            )
            if acc.stale_review_resolved:
                dirty = stale_validation_status.dirty_message(
                    self.config,
                    self.ctx,
                    self.stale_review_status_before,
                )
                if dirty:
                    raise RuntimeError(dirty)
                self.stale_review_validation_output = stale_review.validation_summary(combined_output)
                self.state.iterations[-1]["stale_review_resolved"] = True
        except budgets.BudgetExceeded:
            raise
        except Exception as exc:
            self.cause = exc
            self.state.iterations[-1]["remediation_failed"] = True
            emit_loop_failure_event(
                self.config,
                phase="remediate",
                iteration=iteration,
                reason="remediation_failed",
                error=str(exc),
                ctx=self.ctx,
            )
            return replace(engine_state, event=RemediationDone(exc=exc))
        return replace(engine_state, acc=acc, event=RemediationDone())

    def _run_checks(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        retry_count = engine_state.acc.inner_check_retry_count
        artifact_stem = artifact_label(iteration, retry_count)
        display_label = event_iteration_label(iteration, retry_count)
        checks_outcome = self.ctx.phase_checks.execute(
            ChecksRequest(
                iteration=iteration,
                artifact_label=artifact_stem,
                display_label=display_label,
            ),
            self.ctx,
        )
        check_results = list(checks_outcome.results)
        pending_check_failures = _format_check_failures(check_results)
        timeout_only_failures = bool(pending_check_failures) and _all_failed_checks_are_revrem_timeouts(check_results)
        self.state.set_pending_check_failures(bool(pending_check_failures))
        self.state.iterations[-1]["check_failures"] = len(checks_outcome.failed_commands)
        if check_results:
            self.state.iterations[-1]["checks"] = [
                {
                    "command": shlex.join(result.args),
                    "status": "passed" if result.returncode == 0 else "failed",
                    "artifact": f"check-{artifact_stem}-{index}.txt",
                }
                for index, result in enumerate(check_results, start=1)
            ]
        if engine_state.acc.resolved_route and engine_state.acc.remediation_result_returncode is not None:
            record_routing_outcome(
                config=self.config,
                ctx=self.ctx,
                run_id=self.run_id,
                iteration=iteration,
                remediation_returncode=engine_state.acc.remediation_result_returncode,
                remediation_duration=engine_state.acc.remediation_duration,
                check_results=tuple(check_results),
            )
        acc = replace(
            engine_state.acc,
            pending_check_failures=pending_check_failures,
            failed_check_names=tuple(checks_outcome.failed_commands),
            inner_check_retry_count=(
                self.config.inner_check_retries
                if timeout_only_failures
                else engine_state.acc.inner_check_retry_count
            ),
            commit_retry=False if pending_check_failures else engine_state.acc.commit_retry,
        )
        if acc.stale_review_resolved:
            dirty = stale_validation_status.dirty_message(
                self.config,
                self.ctx,
                self.stale_review_status_before,
            )
            if dirty:
                acc = replace(acc, stale_review_dirty=dirty)
        if timeout_only_failures and self.config.inner_check_retries > retry_count:
            progress_event(
                self.config, "check", str(iteration), "warning",
                "check failures are timeout-only; skipping remediation retry",
                ctx=self.ctx,
            )
        elif pending_check_failures and retry_count >= self.config.inner_check_retries > 0:
            progress_event(
                self.config, "check", str(iteration), "warning",
                "check failures remain after remediation retries; skipping commit",
                ctx=self.ctx,
            )
        return replace(engine_state, acc=acc, event=ChecksDone())

    def _retry_after_checks(self, engine_state: EngineState) -> EngineState:
        retry_count = engine_state.acc.inner_check_retry_count + 1
        progress_event(
            self.config,
            "check",
            str(engine_state.iteration),
            "retry",
            f"check failures will feed remediation retry {retry_count}/{self.config.inner_check_retries}",
            ctx=self.ctx,
        )
        acc = replace(
            engine_state.acc,
            inner_check_retry_count=retry_count,
            remediation_input=(
                engine_state.acc.pending_check_failures
                + "\n\n"
                + engine_state.acc.remediation_input
            ),
        )
        return self._run_remediation(replace(engine_state, acc=acc))

    def _run_commit(self, engine_state: EngineState) -> EngineState:
        result = execute_commit_phase(
            config=self.config,
            ctx=self.ctx,
            iterations=self.state.iterations,
            engine_state=engine_state,
            expected_head=self.expected_head,
        )
        self.cause = result.cause or self.cause
        self.expected_head = result.expected_head
        return result.state

    def _retry_after_commit_hook(self, engine_state: EngineState, action: RetryViaCommitHook) -> EngineState:
        commit_failed = engine_state.event.commit_failed if isinstance(engine_state.event, CommitDone) else None
        if not isinstance(commit_failed, CommitFailed):
            raise RuntimeError(action.hook_output)
        pending_check_failures = format_commit_hook_failure_for_remediation(commit_failed)
        self.state.set_pending_check_failures(True)
        progress_event(
            self.config, "commit", str(engine_state.iteration), "retry",
            "hook output will feed next remediation", ctx=self.ctx,
        )
        acc = replace(engine_state.acc, commit_retry=True, pending_check_failures=pending_check_failures)
        return replace(engine_state, acc=acc, event=LoopStarted(), iteration=engine_state.iteration + 1)


@dataclass(frozen=True)
class RunnerShellResult:
    outcome: RunOutcome
    cause: BaseException | None
    last_review_output: str


def run_iterations(
    *,
    config: LoopConfig,
    state: RunState,
    clock: Clock,
    ctx: RunContext,
    snap: ConfigSnapshot,
    initial_review_output: str,
    run_id: str,
) -> RunnerShellResult:
    executor = _RunnerEngineExecutor(
        config=config,
        state=state,
        clock=clock,
        ctx=ctx,
        run_id=run_id,
        initial_review_output=initial_review_output,
    )
    engine_state = EngineState(
        cfg=snap,
        acc=LoopAccumulator(pending_check_failures=""),
        event=LoopStarted(),
        iteration=1,
    )
    outcome = run_engine(
        engine_state,
        executor,
        max_steps=config.max_iterations * _ENGINE_STEPS_PER_ITERATION + _ENGINE_STEP_BUDGET_OVERHEAD,
    )
    latest_review_output = ""
    if executor.latest_state is not None and isinstance(
        outcome, (OutcomeClear, OutcomeFindings, OutcomeUnknown)
    ):
        latest_review_output = executor.latest_state.acc.last_review_output
    if getattr(outcome, "reason", "") == "stale_review_already_resolved":
        latest_review_output = executor.stale_review_validation_output
    return RunnerShellResult(
        outcome=outcome,
        cause=executor.cause if isinstance(outcome, OutcomeFailed) else None,
        last_review_output=latest_review_output,
    )
