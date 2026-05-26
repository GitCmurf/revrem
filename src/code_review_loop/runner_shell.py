"""Private imperative shell that executes core engine actions.

The pure state machine lives in :mod:`code_review_loop.core.engine`. This
module owns the side-effectful translation from engine actions to phase ports
without importing the public runner facade.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from code_review_loop import artifacts, budgets, diagnostics, policy, prompts_composer, triage
from code_review_loop.adapters.checks import format_check_failures as _format_check_failures
from code_review_loop.adapters.commit import (
    format_commit_hook_failure_for_remediation as format_commit_hook_failure_for_remediation,
)
from code_review_loop.adapters.phase_support import CommitFailed as CommitFailed
from code_review_loop.adapters.phase_support import _combined_output as _combined_output
from code_review_loop.adapters.phase_support import (
    emit_loop_failure_event as emit_loop_failure_event,
)
from code_review_loop.adapters.phase_support import progress_event as progress_event
from code_review_loop.adapters.phase_support import (
    remaining_wall_budget_seconds as remaining_wall_budget_seconds,
)
from code_review_loop.adapters.phase_support import write_artifact as write_artifact
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
    CommandResult,
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


def _build_routing_payload(
    *,
    resolved_route: policy.ResolvedRoute,
    triage_payload: dict[str, Any],
    run_id: str,
    iteration: int,
    remediation_input: str,
    config: LoopConfig,
) -> dict[str, Any]:
    """Assemble the per-iteration routing decision artifact.

    Extracted from the inline ``_run_loop`` body in Wave C2b (TD-004). Pure with
    respect to the loop state: every input is passed explicitly so future
    callers (e.g. snapshot replay) can reconstruct the same artifact without
    re-running the policy resolver.
    """
    eff_harness = resolved_route.harness
    eff_model = resolved_route.model or config.remediation_model or config.model
    eff_reasoning = (
        resolved_route.reasoning_effort
        or config.remediation_reasoning_effort
        or config.reasoning_effort
    )
    eff_sandbox = resolved_route.sandbox
    eff_timeout = (
        int(resolved_route.timeout_seconds)
        if resolved_route.timeout_seconds is not None
        else 300
    )

    effective_route: dict[str, Any] = {
        "route_tier": resolved_route.route_tier,
        "harness": eff_harness,
        "sandbox": eff_sandbox,
        "timeout_seconds": eff_timeout,
    }
    if eff_model:
        effective_route["model"] = eff_model
    if eff_reasoning:
        effective_route["reasoning_effort"] = eff_reasoning

    proposal_present = bool(triage_payload.get("route_proposal"))
    proposal_matches_effective = False
    proposal_overrides: list[str] = []
    proposed_fields: dict[str, Any] = {}
    if proposal_present:
        p = triage_payload["route_proposal"]
        proposed_fields = {
            k: p[k]
            for k in (
                "route_tier",
                "harness",
                "model",
                "reasoning_effort",
                "sandbox",
                "timeout_seconds",
                "rationale",
            )
            if k in p
        }
        comparable_keys = (
            "route_tier",
            "harness",
            "model",
            "reasoning_effort",
            "sandbox",
            "timeout_seconds",
        )
        proposal_overrides = [
            key
            for key in comparable_keys
            if key in proposed_fields and effective_route.get(key) != proposed_fields[key]
        ]
        proposal_matches_effective = not proposal_overrides

    if resolved_route.fallback_applied:
        decision = "fallback_applied"
        original = (
            resolved_route.fallbacks_considered[0]
            if resolved_route.fallbacks_considered
            else "unknown"
        )
        rationale = f"Original route {original!r} fell back to {resolved_route.fallback_applied!r}."
    elif proposal_present and proposal_matches_effective:
        decision = "proposal_accepted"
        rationale = "Model route proposal accepted by policy."
    elif proposal_present:
        decision = "policy_override"
        if proposal_overrides:
            fields = ", ".join(proposal_overrides)
            rationale = (
                "Policy selected the proposed tier but overrode "
                f"proposal field(s): {fields}."
            )
        else:
            rationale = "Policy overrode the model route proposal."
    elif resolved_route.rule_id == "default":
        decision = "default_route_applied"
        rationale = "No model route proposal or rule match; applied default route."
    else:
        decision = "policy_override"
        rationale = "Applied policy based on classification."

    routing_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "iteration": iteration,
        "source_triage_artifact": f"triage-{iteration}.json",
        "policy_decision": {
            "decision": decision,
            "matched_rule_ids": (
                [resolved_route.rule_id]
                if resolved_route.rule_id and resolved_route.rule_id != "default"
                else []
            ),
            "rationale": rationale,
        },
        "effective_route": effective_route,
        "fallbacks_considered": list(resolved_route.fallbacks_considered),
        "prompt": {
            "path": f"remediation-{iteration}-prompt.txt",
            "sha256": prompts_composer.compute_prompt_hash(remediation_input),
            "bytes": len(remediation_input),
            "fragments": list(resolved_route.prompt_fragments),
        },
    }
    if proposal_present:
        routing_payload["model_proposal"] = proposed_fields
    return routing_payload



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
        self.last_review_output = ""
        self.remediation_input = ""
        self.resolved_route: policy.ResolvedRoute | None = None
        self.failed_check_names: list[str] = []
        self.cause: BaseException | None = None
        self.remediation_result: CommandResult | None = None
        self.remediation_duration = 0.0
        self.routing_context_cache: triage.RoutingContextCache = {}

    def execute(self, action: Action, engine_state: EngineState) -> EngineState:
        if isinstance(action, Continue):
            return replace(engine_state, event=LoopStarted(), iteration=engine_state.iteration + 1)
        if isinstance(action, RunReview):
            return self._run_review(engine_state, is_final=action.is_final)
        if isinstance(action, RunTriage):
            return self._run_triage(engine_state)
        if isinstance(action, RunRemediation):
            return self._run_remediation(engine_state)
        if isinstance(action, RunChecks):
            return self._run_checks(engine_state)
        if isinstance(action, RunCommit):
            return self._run_commit(engine_state)
        if isinstance(action, RetryViaCommitHook):
            return self._retry_after_commit_hook(engine_state, action)
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
            self.last_review_output = actionable_review_output(_combined_output(review))
            acc = replace(engine_state.acc, last_review_status=status)
            if status == "unknown" and not acc.pending_check_failures:
                self.iterations.append({"iteration": "final", "review_status": status})
            return replace(engine_state, acc=acc, event=ReviewDone(is_final=True, status=status))

        iteration = engine_state.iteration
        self.resolved_route = None
        self.remediation_result = None
        self.remediation_duration = 0.0
        if iteration == 1 and self.initial_review_output:
            status = cast("Literal['clear', 'findings', 'unknown']", detect_review_status(self.initial_review_output))
            if status == "unknown":
                status = "findings"
            self.last_review_output = self.initial_review_output
            self.iterations.append(
                {
                    "iteration": iteration,
                    "review_status": status,
                    "review_source": str(self.config.initial_review_file),
                }
            )
            acc = replace(engine_state.acc, last_review_status=cast("Literal['clear', 'findings', 'unknown']", status))
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
        self.last_review_output = actionable_review_output(_combined_output(review))
        self.iterations.append({"iteration": iteration, "review_status": status})
        acc = replace(engine_state.acc, last_review_status=status)
        return replace(engine_state, acc=acc, event=ReviewDone(is_final=False, status=status))

    def _run_triage(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        self.remediation_input = self.last_review_output
        if engine_state.acc.pending_check_failures:
            self.remediation_input = engine_state.acc.pending_check_failures + "\n\n" + self.remediation_input
        try:
            source_review_artifact = "review-initial.txt" if iteration == 1 and self.initial_review_output else f"review-{iteration}.txt"
            triage_outcome = self.ctx.phase_triage.execute(
                TriageRequest(
                    iteration=iteration,
                    run_id=self.run_id,
                    source_review_artifact=source_review_artifact,
                    review_output=self.remediation_input,
                ),
                self.ctx,
            )
            self.remediation_input = triage_outcome.handoff
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
                    self.remediation_input = engine_state.acc.pending_check_failures
                return replace(
                    engine_state,
                    event=TriageDone(is_clear=True, suppressed_count=suppressed_count),
                )

            if triage_payload and self.config.triage_contract == "v2" and self.config.profile_v2:
                self._resolve_routing(iteration, triage_payload)
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
        return replace(engine_state, event=TriageDone(is_clear=False))

    def _resolve_routing(self, iteration: int, triage_payload: dict[str, Any]) -> None:
        assert self.config.profile_v2 is not None
        routing_config = self.config.profile_v2.triage.routing
        if routing_config.enabled:
            routing_context = triage.extract_routing_context(
                triage_payload,
                self.config.cwd,
                failed_checks=tuple(self.failed_check_names),
                cache=self.routing_context_cache,
            )
            model_proposal = triage_payload.get("route_proposal", {})
            self.resolved_route = policy.resolve_routing(
                self.config.profile_v2,
                routing_context,
                model_proposal_tier=model_proposal.get("route_tier"),
                max_timeout_seconds=remaining_wall_budget_seconds(self.config, self.ctx),
            )
            progress_event(
                self.config,
                "triage",
                str(iteration),
                "routing",
                f"routed to {self.resolved_route.route_tier} ({self.resolved_route.harness})",
                ctx=self.ctx,
            )
        else:
            self.resolved_route = policy.ResolvedRoute(
                route_tier="default",
                harness=self.config.remediation_harness,
                model=self.config.remediation_model or self.config.model,
                reasoning_effort=self.config.remediation_reasoning_effort or self.config.reasoning_effort,
                timeout_seconds=self.config.remediation_timeout_seconds,
                sandbox=self.config.exec_sandbox,
                prompt_fragments=(),
                allow_model_deescalation=True,
                rule_id="default",
            )

        self.remediation_input = prompts_composer.compose_remediation_prompt(
            self.config.cwd,
            triage_payload,
            self.resolved_route,
            self.remediation_input,
            max_chars=self.config.max_remediation_input_chars,
            trusted_repo=self.config.trusted_repo,
        )
        routing_payload = _build_routing_payload(
            resolved_route=self.resolved_route,
            triage_payload=triage_payload,
            run_id=self.run_id,
            iteration=iteration,
            remediation_input=self.remediation_input,
            config=self.config,
        )
        try:
            triage.validate_routing_payload(routing_payload)
        except triage.TriageValidationError as exc:
            issue = triage.invalid_triage_issue(exc, iteration=iteration)
            artifacts.write_json_artifact(
                self.config.artifact_dir,
                f"diagnostics-{iteration}.json",
                diagnostics.doctor_payload([issue]),
            )
            progress_event(
                self.config,
                "triage",
                str(iteration),
                "invalid",
                f"routing payload schema validation failed: {exc}",
                ctx=self.ctx,
            )
            raise RuntimeError(f"invalid routing decision artifact for iteration {iteration}: {exc}") from exc

        triage.write_routing_artifact(self.config.artifact_dir, iteration, routing_payload)
        if self.ctx.event_sink:
            self.ctx.event_sink.emit("routing_decision", phase="triage", iteration=iteration, payload=routing_payload)
        write_artifact(self.config.artifact_dir / f"remediation-{iteration}-prompt.txt", self.remediation_input)

    def _run_remediation(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        if not self.config.triage_enabled:
            self.remediation_input = self.last_review_output
            if engine_state.acc.pending_check_failures:
                self.remediation_input = engine_state.acc.pending_check_failures + "\n\n" + self.remediation_input
        try:
            rem_start_time = self.clock.monotonic()
            rem_outcome = self.ctx.phase_remediation.execute(
                RemediationRequest(
                    iteration=iteration,
                    remediation_input=self.remediation_input,
                    resolved_route=self.resolved_route,
                ),
                self.ctx,
            )
            self.remediation_result = rem_outcome.result
            self.remediation_duration = self.clock.monotonic() - rem_start_time
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
        return replace(engine_state, event=RemediationDone())

    def _run_checks(self, engine_state: EngineState) -> EngineState:
        iteration = engine_state.iteration
        checks_outcome = self.ctx.phase_checks.execute(ChecksRequest(iteration=iteration), self.ctx)
        check_results = list(checks_outcome.results)
        self.failed_check_names = list(checks_outcome.failed_commands)
        pending_check_failures = _format_check_failures(check_results)
        self.state.set_pending_check_failures(bool(pending_check_failures))
        self.iterations[-1]["check_failures"] = len(self.failed_check_names)
        if self.resolved_route and self.remediation_result is not None:
            outcome_payload = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "iteration": iteration,
                "source_routing_artifact": f"routing-{iteration}.json",
                "exit_code": self.remediation_result.returncode,
                "wall_time_seconds": round(self.remediation_duration, 3),
                "checks_passed": all(result.returncode == 0 for result in check_results),
            }
            triage.write_routing_outcome_artifact(self.config.artifact_dir, iteration, outcome_payload)
            if self.ctx.event_sink:
                self.ctx.event_sink.emit("routing_outcome", phase="remediate", iteration=iteration, payload=outcome_payload)
        acc = replace(
            engine_state.acc,
            pending_check_failures=pending_check_failures,
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
    outcome = run_engine(engine_state, executor, max_steps=config.max_iterations * 8 + 4)
    latest_review_output = executor.last_review_output if isinstance(outcome, OutcomeClear) else ""
    return RunnerShellResult(
        outcome=outcome,
        cause=executor.cause,
        last_review_output=latest_review_output,
    )
