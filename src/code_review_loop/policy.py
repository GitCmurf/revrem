"""Triage routing policy engine."""

from __future__ import annotations

from dataclasses import dataclass

from code_review_loop.core.routing_types import (
    Profile,
    ResolvedRoute,
    TriageRouteConfig,
    TriageRoutingRule,
)


@dataclass(frozen=True)
class RoutingContext:
    domain_tags: tuple[str, ...]
    risk_level: str
    refactor_depth: str
    module_count: int
    safety_signals: tuple[str, ...]
    failed_checks: tuple[str, ...] = ()


def check_route_capabilities(route_cfg: TriageRouteConfig) -> list[str]:
    """Verify that the harness for a route is implemented and supports required capabilities."""
    from code_review_loop.harnesses import harness_registry

    spec = harness_registry().get(route_cfg.harness)
    if not spec:
        return [f"Unknown harness: {route_cfg.harness}"]
    if not spec.implemented:
        return [f"Harness {route_cfg.harness!r} is valid syntax, but not yet implemented."]
    if not spec.capabilities:
        return [f"Harness {route_cfg.harness!r} has no capabilities defined."]

    caps = spec.capabilities
    issues = []
    if not caps.remediation_supported:
        issues.append(f"Harness {route_cfg.harness!r} does not support remediation.")
    if not caps.non_interactive:
        issues.append(
            f"Harness {route_cfg.harness!r} is not suitable for automated loops (requires interactive session)."
        )
    if route_cfg.sandbox not in caps.sandbox_modes:
        issues.append(
            f"Harness {route_cfg.harness!r} does not support sandbox mode {route_cfg.sandbox!r}. "
            f"Supported: {', '.join(caps.sandbox_modes)}"
        )
    # Note: timeouts are enforced by RevRem's own subprocess wrapper
    # (run_with_timeout / default_runner), independent of whether the harness
    # CLI exposes a native timeout flag. A route with timeout_seconds is
    # therefore valid on any harness; caps.timeout_supported is metadata only.
    if caps.supported_models and route_cfg.model and route_cfg.model not in caps.supported_models:
        issues.append(
            f"Harness {route_cfg.harness!r} does not support model {route_cfg.model!r}. "
            f"Supported: {', '.join(caps.supported_models)}"
        )

    return issues


def check_route_budget(
    route_cfg: TriageRouteConfig,
    *,
    max_timeout_seconds: float | None = None,
) -> list[str]:
    if (
        max_timeout_seconds is not None
        and route_cfg.timeout_seconds is not None
        and route_cfg.timeout_seconds > max_timeout_seconds
    ):
        return [
            f"Route timeout {route_cfg.timeout_seconds:g}s exceeds remaining wall budget "
            f"{max_timeout_seconds:g}s."
        ]
    return []


def resolve_routing(
    profile: Profile,
    context: RoutingContext,
    model_proposal_tier: str | None = None,
    max_timeout_seconds: float | None = None,
) -> ResolvedRoute:
    routing_config = profile.triage.routing

    # 1. Start with initial route (from rule match or default)
    matched_rule: TriageRoutingRule | None = None
    if routing_config.enabled:
        for rule in routing_config.rule:
            if _match_rule(rule, context):
                matched_rule = rule
                break

    if matched_rule:
        route_tier = matched_rule.then.route or routing_config.default_route
        rule_escalation = matched_rule.then.allow_model_escalation
        allow_escalation = (
            rule_escalation
            if rule_escalation is not None
            else routing_config.allow_model_escalation
        )
        allow_deescalation = matched_rule.then.allow_model_deescalation
        prompt_fragments = matched_rule.then.prompt_fragments
    else:
        route_tier = routing_config.default_route
        allow_escalation = routing_config.allow_model_escalation
        allow_deescalation = True  # Default route allows de-escalation by default
        prompt_fragments = ()

    # 2. Consider model proposal
    effective_tier = route_tier
    if (
        model_proposal_tier
        and model_proposal_tier in profile.triage.routes
        and model_proposal_tier != route_tier
    ):
        # Apply the model proposal only when its direction relative to the policy
        # route is known and permitted. direction None (uncomparable tiers) or 0
        # (same rank) leaves the policy route in place.
        direction = _tier_direction(model_proposal_tier, route_tier)
        escalation_ok = direction == 1 and allow_escalation
        deescalation_ok = direction == -1 and allow_deescalation
        if escalation_ok or deescalation_ok:
            effective_tier = model_proposal_tier

    # 3. Resolve with fallback loop for implementation status
    fallbacks_considered: list[str] = []
    visited_tiers: set[str] = set()
    current_tier = effective_tier

    while True:
        if current_tier in visited_tiers:
            cycle = " -> ".join((*fallbacks_considered, current_tier))
            raise RuntimeError(f"Circular fallback detected in route chain: {cycle}.")
        visited_tiers.add(current_tier)

        if current_tier not in profile.triage.routes:
            if routing_config.strict_on_unavailable_route:
                raise ValueError(f"Route tier {current_tier!r} not defined in profile.")
            if current_tier == routing_config.default_route:
                raise ValueError(f"Default route tier {current_tier!r} not defined in profile.")
            fallbacks_considered.append(current_tier)
            current_tier = routing_config.default_route
            continue

        route_cfg = profile.triage.routes[current_tier]

        issues = [
            *check_route_capabilities(route_cfg),
            *check_route_budget(route_cfg, max_timeout_seconds=max_timeout_seconds),
        ]
        if not issues:
            return ResolvedRoute(
                route_tier=current_tier,
                harness=route_cfg.harness,
                model=route_cfg.model,
                reasoning_effort=route_cfg.reasoning_effort,
                timeout_seconds=route_cfg.timeout_seconds,
                sandbox=route_cfg.sandbox,
                prompt_fragments=prompt_fragments,
                allow_model_deescalation=allow_deescalation,
                rule_id=matched_rule.id if matched_rule else "default",
                fallbacks_considered=tuple(fallbacks_considered),
                fallback_applied=current_tier if fallbacks_considered else None,
            )

        if routing_config.strict_on_unavailable_route:
            fallback_note = (
                f" Configured fallback {route_cfg.fallback!r} is ignored because strict routing is enabled."
                if route_cfg.fallback
                else " Strict routing is enabled."
            )
            raise RuntimeError(
                f"Route {current_tier!r} (harness {route_cfg.harness!r}) is unavailable or lacks "
                f"required capabilities: {'; '.join(issues)}.{fallback_note}"
            )

        if not route_cfg.fallback:
            raise RuntimeError(
                f"Route {current_tier!r} (harness {route_cfg.harness!r}) is unavailable or lacks "
                f"required capabilities: {'; '.join(issues)}. No explicit fallback is configured."
            )

        fallbacks_considered.append(current_tier)
        current_tier = route_cfg.fallback


TIER_RANK = {
    "security-specialist": 200,
    "codex-frontier": 100,
    "frontier": 100,
    "frontier-thinking": 100,
    "gemini-pro": 90,
    "codex-midi": 50,
    "midtier-coder": 50,
    "midtier": 50,
    "efficient": 10,
    "efficient-coder": 10,
}


def _tier_direction(proposed: str, current: str) -> int | None:
    """Compare two route tiers by rank.

    Returns 1 if ``proposed`` outranks ``current``, -1 if it is lower, 0 if
    equal, and None when the tiers cannot be compared (either is outside the
    known ranking). An uncomparable proposal must not override the policy route.
    """
    proposed_rank = TIER_RANK.get(proposed)
    current_rank = TIER_RANK.get(current)
    if proposed_rank is None or current_rank is None:
        return None
    if proposed_rank > current_rank:
        return 1
    if proposed_rank < current_rank:
        return -1
    return 0


def _match_rule(rule: TriageRoutingRule, context: RoutingContext) -> bool:
    cond = rule.when
    if cond.risk_level_min and not _risk_gte(context.risk_level, cond.risk_level_min):
        return False
    if cond.risk_level_max and not _risk_lte(context.risk_level, cond.risk_level_max):
        return False

    if cond.refactor_depth_any and context.refactor_depth not in cond.refactor_depth_any:
        return False

    if cond.module_count_gte is not None and context.module_count < cond.module_count_gte:
        return False
    if cond.module_count_lt is not None and context.module_count >= cond.module_count_lt:
        return False

    if cond.domain_tags_any and not any(tag in cond.domain_tags_any for tag in context.domain_tags):
        return False

    if cond.safety_signals_any and not any(
        s in cond.safety_signals_any for s in context.safety_signals
    ):
        return False

    return not cond.failed_checks_any or any(
        c in cond.failed_checks_any for c in context.failed_checks
    )


RISK_ORDER = {"trivial": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _risk_gte(actual: str, minimum: str) -> bool:
    return RISK_ORDER.get(actual, 1) >= RISK_ORDER.get(minimum, 1)


def _risk_lte(actual: str, maximum: str) -> bool:
    return RISK_ORDER.get(actual, 1) <= RISK_ORDER.get(maximum, 1)
