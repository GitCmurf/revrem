"""Deterministic routing policy engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from code_review_loop.profiles import Profile, TriageRoutingRule


@dataclass(frozen=True)
class RoutingContext:
    domain_tags: tuple[str, ...]
    risk_level: str
    refactor_depth: str
    module_count: int
    failed_checks: tuple[str, ...]
    safety_signals: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedRoute:
    route_tier: str
    harness: str
    model: str | None
    reasoning_effort: str | None
    timeout_seconds: float | None
    sandbox: str
    prompt_fragments: tuple[str, ...]
    allow_model_deescalation: bool
    rule_id: str | None = None
    fallback_applied: str | None = None
    fallbacks_considered: tuple[str, ...] = field(default_factory=tuple)


def resolve_routing(
    profile: Profile,
    context: RoutingContext,
    model_proposal_tier: str | None = None,
) -> ResolvedRoute:
    routing = profile.triage.routing
    if not routing.enabled:
        # Fallback to standard remediation config if routing is disabled
        return ResolvedRoute(
            route_tier="legacy-remediation",
            harness=profile.remediation.harness,
            model=profile.remediation.model,
            reasoning_effort=profile.remediation.reasoning_effort,
            timeout_seconds=profile.remediation.timeout_seconds,
            sandbox=profile.runtime.exec_sandbox,
            prompt_fragments=(),
            allow_model_deescalation=True,
        )

    matched_rule = None
    for rule in routing.rule:
        if _matches(rule, context):
            matched_rule = rule
            break

    if matched_rule:
        route_tier = matched_rule.then.route or routing.default_route
        rule_id = matched_rule.id
        prompt_fragments = matched_rule.then.prompt_fragments
        allow_model_deescalation = matched_rule.then.allow_model_deescalation
        allow_model_escalation = (
            matched_rule.then.allow_model_escalation
            if matched_rule.then.allow_model_escalation is not None
            else routing.allow_model_escalation
        )
    else:
        route_tier = routing.default_route
        rule_id = "default"
        prompt_fragments = ()
        allow_model_deescalation = True
        allow_model_escalation = routing.allow_model_escalation

    # Model escalation: if model proposed a higher tier and policy allows it
    effective_tier = route_tier
    if model_proposal_tier and model_proposal_tier != route_tier:
        if _is_higher_tier(model_proposal_tier, route_tier):
            if allow_model_escalation:
                effective_tier = model_proposal_tier
            else:
                effective_tier = route_tier
        elif not allow_model_deescalation:
            # De-escalation forbidden by policy
            effective_tier = route_tier
        else:
            effective_tier = model_proposal_tier

    fallbacks_considered = []
    current_tier = effective_tier

    while True:
        if current_tier not in profile.triage.routes:
            raise ValueError(f"Resolved to unknown route tier: {current_tier}")

        route_config = profile.triage.routes[current_tier]

        # Check if harness is implemented
        from code_review_loop import harnesses
        spec = harnesses.harness_registry().get(route_config.harness)
        if spec and spec.implemented:
            return ResolvedRoute(
                route_tier=current_tier,
                harness=route_config.harness,
                model=route_config.model,
                reasoning_effort=route_config.reasoning_effort,
                timeout_seconds=route_config.timeout_seconds,
                sandbox=route_config.sandbox,
                prompt_fragments=prompt_fragments,
                allow_model_deescalation=allow_model_deescalation,
                rule_id=rule_id,
                fallback_applied=current_tier if current_tier != effective_tier else None,
                fallbacks_considered=tuple(fallbacks_considered),
            )

        # Try fallback
        if not route_config.fallback:
            raise ValueError(f"Route {current_tier!r} uses unimplemented harness {route_config.harness!r} and has no fallback.")

        fallbacks_considered.append(current_tier)
        current_tier = route_config.fallback
        if current_tier in fallbacks_considered:
            raise ValueError(f"Circular fallback detected: {' -> '.join(fallbacks_considered)} -> {current_tier}")


def _matches(rule: TriageRoutingRule, context: RoutingContext) -> bool:
    w = rule.when
    if w.domain_tags_any and not any(tag in context.domain_tags for tag in w.domain_tags_any):
        return False
    if w.risk_level_any and context.risk_level not in w.risk_level_any:
        return False
    if w.risk_level_max and _is_higher_risk(context.risk_level, w.risk_level_max):
        return False
    if w.refactor_depth_any and context.refactor_depth not in w.refactor_depth_any:
        return False
    if w.module_count_gte is not None and context.module_count < w.module_count_gte:
        return False
    if w.module_count_lt is not None and context.module_count >= w.module_count_lt:
        return False
    if w.safety_signals_any and not any(s in context.safety_signals for s in w.safety_signals_any):
        return False
    if w.failed_checks_any and not any(c in context.failed_checks for c in w.failed_checks_any):
        return False
    return True


_RISK_ORDER = {"trivial": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

def _is_higher_risk(actual: str, maximum: str) -> bool:
    return _RISK_ORDER.get(actual, 0) > _RISK_ORDER.get(maximum, 0)


_TIER_ORDER = {
    "efficient-coder": 0,
    "midtier-coder": 1,
    "frontier-thinking": 2,
    "security-specialist": 3,
}

def _is_higher_tier(proposed: str, baseline: str) -> bool:
    return _TIER_ORDER.get(proposed, 0) > _TIER_ORDER.get(baseline, 0)
