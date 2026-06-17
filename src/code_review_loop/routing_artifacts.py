"""Routing resolution and artifact emission for the runner shell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from code_review_loop import (
    artifacts,
    diagnostics,
    policy,
    prompts_composer,
    routing_timeouts,
    triage,
)
from code_review_loop.adapters.phase_support import (
    progress_event,
    remaining_wall_budget_seconds,
    write_artifact,
)
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RunContext


@dataclass(frozen=True)
class RoutingResolution:
    resolved_route: policy.ResolvedRoute
    remediation_input: str


def resolve_and_record_routing(
    *,
    config: LoopConfig,
    ctx: RunContext,
    run_id: str,
    iteration: int,
    triage_payload: dict[str, Any],
    remediation_input: str,
    failed_check_names: tuple[str, ...],
    cache: triage.RoutingContextCache,
) -> RoutingResolution:
    """Resolve a v2 remediation route and write its operator-visible artifacts."""

    if config.profile_v2 is None:
        raise RuntimeError("v2 routing requires profile_v2 configuration")
    resolved_route = _resolve_route(
        config=config,
        ctx=ctx,
        iteration=iteration,
        triage_payload=triage_payload,
        failed_check_names=failed_check_names,
        cache=cache,
    )
    composed_input = prompts_composer.compose_remediation_prompt(
        config.cwd,
        triage_payload,
        resolved_route,
        remediation_input,
        max_chars=config.max_remediation_input_chars,
        trusted_repo=config.trusted_repo,
    )
    routing_payload = build_routing_payload(
        resolved_route=resolved_route,
        triage_payload=triage_payload,
        run_id=run_id,
        iteration=iteration,
        remediation_input=composed_input,
        config=config,
    )
    _validate_and_write_routing_payload(
        config=config,
        ctx=ctx,
        iteration=iteration,
        routing_payload=routing_payload,
        remediation_input=composed_input,
    )
    return RoutingResolution(resolved_route=resolved_route, remediation_input=composed_input)


def _resolve_route(
    *,
    config: LoopConfig,
    ctx: RunContext,
    iteration: int,
    triage_payload: dict[str, Any],
    failed_check_names: tuple[str, ...],
    cache: triage.RoutingContextCache,
) -> policy.ResolvedRoute:
    if config.profile_v2 is None:
        raise RuntimeError("v2 routing requires profile_v2 configuration")
    routing_config = config.profile_v2.triage.routing
    if not routing_config.enabled:
        return policy.ResolvedRoute(
            route_tier="default",
            harness=config.remediation_harness,
            model=config.remediation_model or config.model,
            reasoning_effort=config.remediation_reasoning_effort or config.reasoning_effort,
            timeout_seconds=config.remediation_timeout_seconds,
            sandbox=config.exec_sandbox,
            prompt_fragments=(),
            allow_model_deescalation=True,
            rule_id="default",
        )

    routing_context = triage.extract_routing_context(
        triage_payload,
        config.cwd,
        failed_checks=failed_check_names,
        cache=cache,
    )
    model_proposal = triage_payload.get("route_proposal", {})
    resolved_route = policy.resolve_routing(
        config.profile_v2,
        routing_context,
        model_proposal_tier=model_proposal.get("route_tier"),
        max_timeout_seconds=remaining_wall_budget_seconds(config, ctx),
    )
    progress_event(
        config,
        "triage",
        str(iteration),
        "routing",
        f"routed to {resolved_route.route_tier} ({resolved_route.harness})",
        ctx=ctx,
    )
    return resolved_route


def build_routing_payload(
    *,
    resolved_route: policy.ResolvedRoute,
    triage_payload: dict[str, Any],
    run_id: str,
    iteration: int,
    remediation_input: str,
    config: LoopConfig,
) -> dict[str, Any]:
    """Assemble the per-iteration routing decision artifact."""

    effective_route = _effective_route(resolved_route, config)
    proposal_present = bool(triage_payload.get("route_proposal"))
    proposal_matches_effective = False
    proposal_overrides: list[str] = []
    proposed_fields: dict[str, Any] = {}
    if proposal_present:
        proposed_fields = _proposed_route_fields(triage_payload)
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

    decision, rationale = _policy_decision(
        resolved_route=resolved_route,
        proposal_present=proposal_present,
        proposal_matches_effective=proposal_matches_effective,
        proposal_overrides=proposal_overrides,
    )
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
            "bytes": len(remediation_input.encode("utf-8")),
            "fragments": list(resolved_route.prompt_fragments),
        },
    }
    if proposal_present:
        routing_payload["model_proposal"] = proposed_fields
    return routing_payload


def _effective_route(resolved_route: policy.ResolvedRoute, config: LoopConfig) -> dict[str, Any]:
    eff_model = resolved_route.model or config.remediation_model or config.model
    eff_reasoning = (
        resolved_route.reasoning_effort
        or config.remediation_reasoning_effort
        or config.reasoning_effort
    )
    effective_route: dict[str, Any] = {
        "route_tier": resolved_route.route_tier,
        "harness": resolved_route.harness,
        "sandbox": resolved_route.sandbox,
    }
    timeout = _artifact_timeout_seconds(resolved_route, config)
    effective_route["timeout_seconds"] = timeout if timeout is not None else 0
    if eff_model:
        effective_route["model"] = eff_model
    if eff_reasoning:
        effective_route["reasoning_effort"] = eff_reasoning
    return effective_route


def _artifact_timeout_seconds(
    resolved_route: policy.ResolvedRoute, config: LoopConfig
) -> float | int | None:
    return routing_timeouts.effective_route_timeout_seconds(config, resolved_route)


def _proposed_route_fields(triage_payload: dict[str, Any]) -> dict[str, Any]:
    proposal = triage_payload["route_proposal"]
    return {
        key: proposal[key]
        for key in (
            "route_tier",
            "harness",
            "model",
            "reasoning_effort",
            "sandbox",
            "timeout_seconds",
            "rationale",
        )
        if key in proposal
    }


def _policy_decision(
    *,
    resolved_route: policy.ResolvedRoute,
    proposal_present: bool,
    proposal_matches_effective: bool,
    proposal_overrides: list[str],
) -> tuple[str, str]:
    if resolved_route.fallback_applied:
        original = (
            resolved_route.fallbacks_considered[0]
            if resolved_route.fallbacks_considered
            else "unknown"
        )
        return (
            "fallback_applied",
            f"Original route {original!r} fell back to {resolved_route.fallback_applied!r}.",
        )
    if proposal_present and proposal_matches_effective:
        if resolved_route.rule_id and resolved_route.rule_id != "default":
            return (
                "proposal_accepted",
                f"Model route proposal accepted; routing rule {resolved_route.rule_id!r} "
                "also matched.",
            )
        return "proposal_accepted", "Model route proposal accepted by policy."
    if resolved_route.rule_id and resolved_route.rule_id != "default":
        if proposal_present and proposal_overrides:
            fields = ", ".join(proposal_overrides)
            return (
                "policy_override",
                f"Applied routing rule {resolved_route.rule_id!r} and overrode "
                f"proposal field(s): {fields}.",
            )
        return (
            "policy_override",
            f"Applied routing rule {resolved_route.rule_id!r} based on triage classification.",
        )
    if proposal_present:
        if proposal_overrides:
            fields = ", ".join(proposal_overrides)
            return (
                "policy_override",
                f"Policy selected the proposed tier but overrode proposal field(s): {fields}.",
            )
        return "policy_override", "Policy overrode the model route proposal."
    if resolved_route.rule_id == "default":
        return (
            "default_route_applied",
            "No model route proposal or rule match; applied default route.",
        )
    return "policy_override", "Policy selected a non-default route."


def _validate_and_write_routing_payload(
    *,
    config: LoopConfig,
    ctx: RunContext,
    iteration: int,
    routing_payload: dict[str, Any],
    remediation_input: str,
) -> None:
    try:
        triage.validate_routing_payload(routing_payload)
    except triage.TriageValidationError as exc:
        issue = triage.invalid_triage_issue(exc, iteration=iteration)
        artifacts.write_json_artifact(
            config.artifact_dir,
            f"diagnostics-{iteration}.json",
            diagnostics.doctor_payload([issue]),
        )
        progress_event(
            config,
            "triage",
            str(iteration),
            "invalid",
            f"routing payload schema validation failed: {exc}",
            ctx=ctx,
        )
        raise RuntimeError(
            f"invalid routing decision artifact for iteration {iteration}: {exc}"
        ) from exc

    triage.write_routing_artifact(config.artifact_dir, iteration, routing_payload)
    if ctx.event_sink:
        ctx.event_sink.emit(
            "routing_decision", phase="triage", iteration=iteration, payload=routing_payload
        )
    write_artifact(config.artifact_dir / f"remediation-{iteration}-prompt.txt", remediation_input)


def record_routing_outcome(
    *,
    config: LoopConfig,
    ctx: RunContext,
    run_id: str,
    iteration: int,
    remediation_returncode: int,
    remediation_duration: float,
    check_results: tuple[CommandResult, ...],
) -> None:
    """Write the routing outcome artifact paired with a prior routing decision."""

    outcome_payload = {
        "schema_version": "1.0",
        "run_id": run_id,
        "iteration": iteration,
        "source_routing_artifact": f"routing-{iteration}.json",
        "exit_code": remediation_returncode,
        "wall_time_seconds": round(remediation_duration, 3),
        "checks_passed": all(result.returncode == 0 for result in check_results),
    }
    triage.write_routing_outcome_artifact(config.artifact_dir, iteration, outcome_payload)
    if ctx.event_sink:
        ctx.event_sink.emit(
            "routing_outcome", phase="remediate", iteration=iteration, payload=outcome_payload
        )
