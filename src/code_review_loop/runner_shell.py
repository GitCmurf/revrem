"""Private imperative shell that executes core engine actions.

The pure state machine lives in :mod:`code_review_loop.core.engine`. This
module owns the side-effectful translation from engine actions to phase ports
without importing the public runner facade.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from code_review_loop import budgets, triage
from code_review_loop.adapters.checks import format_check_failures as _format_check_failures
from code_review_loop.adapters.commit import (
    format_commit_hook_failure_for_remediation,
)
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
    RetryViaCommitHook,
    ReviewDone,
    RunChecks,
    RunCommit,
    RunRemediation,
    RunReview,
    RunTriage,
    TriageDone,
)
from code_review_loop.core.engine import (
    run as run_engine,
)
from code_review_loop.core.outcome import OutcomeClear, RunOutcome
from code_review_loop.core.ports import (
    ChecksRequest,
    CommitRequest,
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
from code_review_loop.routing_artifacts import record_routing_outcome, resolve_and_record_routing

_ENGINE_STEPS_PER_ITERATION = 8
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

    def execute(self, action: Action, engine_state: EngineState) -> EngineState:
        if isinstance(action, Continue):
            next_state = replace(engine_state, event=LoopStarted(), iteration=engine_state.iteration + 1)
            self.latest_state = next_state
            return next_state
        if isinstance(action, RunReview):
            next_state = self._run_review(engine_state, is_final=action.is_final)
            self.latest_state = next_state
            return next_state
        if isinstance(action, RunTriage):
            next_state = self._run_triage(engine_state)
            self.latest_state = next_state
            return next_state
        if isinstance(action, RunRemediation):
            next_state = self._run_remediation(engine_state)
            self.latest_state = next_state
            return next_state
        if isinstance(action, RunChecks):
            next_state = self._run_checks(engine_state)
            self.latest_state = next_state
            return next_state
        if isinstance(action, RunCommit):
            next_state = self._run_commit(engine_state)
            self.latest_state = next_state
            return next_state
        if isinstance(action, RetryViaCommitHook):
            next_state = self._retry_after_commit_hook(engine_state, action)
            self.latest_state = next_state
            return next_state
        raise AssertionError(f"engine executor received terminal action: {action!r}")

    @property
    def iterations(self) -> list[dict[str, object]]:
        return self.state.iterations

    def _run_review(self, engine_state: EngineState, *, is_final: bool) -> EngineState:
        if is_final:
            try:
                outcome = self.ctx.phase_review.execute(
                    ReviewRequest(artifact_label="review-final", display_label="final"),
                    self.ctx,
                )
            except RuntimeError as exc:
                self.cause = exc
                self.iterations.append({"iteration": "final", "review_failed": True})
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
                self.iterations.append({"iteration": "final", "review_status": status})
            return replace(engine_state, acc=acc, event=ReviewDone(is_final=True, status=status))

        iteration = engine_state.iteration
        acc = replace(
            engine_state.acc,
            resolved_route=None,
            remediation_result_returncode=None,
            remediation_duration=0.0,
        )
        if iteration == 1 and self.initial_review_output:
            status = cast("Literal['clear', 'findings', 'unknown']", detect_review_status(self.initial_review_output))
            if status == "unknown":
                status = "findings"
            self.iterations.append(
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
            self.iterations.append({"iteration": iteration, "review_failed": True})
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
        self.iterations.append({"iteration": iteration, "review_status": status})
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
                self.iterations[-1]["suppressed_findings_count"] = suppressed_count
            if triage_no_actionable:
                if suppressed_count:
                    self.iterations[-1]["suppressed_findings"] = True
                    self.state.set_suppressed_findings_count(suppressed_count)
                if engine_state.acc.pending_check_failures:
                    acc = replace(acc, remediation_input=engine_state.acc.pending_check_failures)
                return replace(
                    engine_state,
                    acc=acc,
                    event=TriageDone(is_clear=True, suppressed_count=suppressed_count),
                )

            if triage_payload and self.config.triage_contract == "v2" and self.config.profile_v2:
                acc = self._resolve_routing(iteration, triage_payload, acc)
        except budgets.BudgetExceeded:
            raise
        except Exception as exc:
            self.cause = exc
            self.iterations[-1]["triage_failed"] = True
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

    def _resolve_routing(
        self,
        iteration: int,
        triage_payload: dict[str, Any],
        acc: LoopAccumulator,
    ) -> LoopAccumulator:
        resolution = resolve_and_record_routing(
            config=self.config,
            ctx=self.ctx,
            run_id=self.run_id,
            iteration=iteration,
            triage_payload=triage_payload,
            remediation_input=acc.remediation_input,
            failed_check_names=acc.failed_check_names,
            cache=self.routing_context_cache,
        )
        return replace(
            acc,
            resolved_route=resolution.resolved_route,
            remediation_input=resolution.remediation_input,
        )

    def _run_remediation(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        remediation_input = engine_state.acc.remediation_input
        if not self.config.triage_enabled:
            remediation_input = engine_state.acc.last_review_output
            if engine_state.acc.pending_check_failures:
                remediation_input = engine_state.acc.pending_check_failures + "\n\n" + remediation_input
        try:
            rem_start_time = self.clock.monotonic()
            rem_outcome = self.ctx.phase_remediation.execute(
                RemediationRequest(
                    iteration=iteration,
                    remediation_input=remediation_input,
                    resolved_route=engine_state.acc.resolved_route,
                ),
                self.ctx,
            )
            acc = replace(
                engine_state.acc,
                remediation_input=remediation_input,
                remediation_result_returncode=rem_outcome.result.returncode,
                remediation_duration=self.clock.monotonic() - rem_start_time,
            )
        except budgets.BudgetExceeded:
            raise
        except Exception as exc:
            self.cause = exc
            self.iterations[-1]["remediation_failed"] = True
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
        checks_outcome = self.ctx.phase_checks.execute(ChecksRequest(iteration=iteration), self.ctx)
        check_results = list(checks_outcome.results)
        pending_check_failures = _format_check_failures(check_results)
        self.state.set_pending_check_failures(bool(pending_check_failures))
        self.iterations[-1]["check_failures"] = len(checks_outcome.failed_commands)
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
            commit_retry=False if pending_check_failures else engine_state.acc.commit_retry,
        )
        return replace(engine_state, acc=acc, event=ChecksDone())

    def _run_commit(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        try:
            commit_outcome = self.ctx.phase_commit.execute(
                CommitRequest(iteration=iteration, retrying=engine_state.acc.commit_retry),
                self.ctx,
            )
            self.iterations[-1]["commit_status"] = commit_outcome.status
        except CommitFailed as exc:
            self.cause = exc
            self.iterations[-1]["commit_status"] = exc.kind
            self.iterations[-1]["commit_failed"] = True
            self.iterations[-1]["commit_artifact"] = str(exc.artifact_path)
            return replace(engine_state, event=CommitDone(status=exc.kind, commit_failed=exc))
        except budgets.BudgetExceeded:
            raise
        except Exception as exc:
            self.cause = exc
            self.iterations[-1]["commit_failed"] = True
            emit_loop_failure_event(
                self.config,
                phase="commit",
                iteration=iteration,
                reason="commit_failed",
                error=str(exc),
                ctx=self.ctx,
            )
            return replace(engine_state, event=CommitDone(status=None, other_exc=exc))
        return replace(
            engine_state,
            event=CommitDone(status=cast("str | None", self.iterations[-1].get("commit_status"))),
        )

    def _retry_after_commit_hook(self, engine_state: EngineState, action: RetryViaCommitHook) -> EngineState:
        commit_failed = engine_state.event.commit_failed if isinstance(engine_state.event, CommitDone) else None
        if not isinstance(commit_failed, CommitFailed):
            raise RuntimeError(action.hook_output)
        pending_check_failures = format_commit_hook_failure_for_remediation(commit_failed)
        self.state.set_pending_check_failures(True)
        progress_event(
            self.config,
            "commit",
            str(engine_state.iteration),
            "retry",
            "hook output will feed next remediation",
            ctx=self.ctx,
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
    latest_review_output = (
        executor.latest_state.acc.last_review_output
        if executor.latest_state is not None and isinstance(outcome, OutcomeClear)
        else ""
    )
    return RunnerShellResult(
        outcome=outcome,
        cause=executor.cause,
        last_review_output=latest_review_output,
    )
