"""Triage routing policy engine."""

from __future__ import annotations

from dataclasses import dataclass

from code_review_loop.profiles import Profile, TriageRoutingRule


@dataclass(frozen=True)
class RoutingContext:
    domain_tags: tuple[str, ...]
    risk_level: str
    refactor_depth: str
    module_count: int
    safety_signals: tuple[str, ...]
    failed_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedRoute:
    route_tier: str
    harness: str
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    sandbox: str = "workspace-write"
    prompt_fragments: tuple[str, ...] = ()
    allow_model_deescalation: bool = True
    rule_id: str | None = None
    fallbacks_considered: tuple[str, ...] = ()
    fallback_applied: str | None = None


def resolve_routing(
    profile: Profile,
    context: RoutingContext,
    model_proposal_tier: str | None = None,
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
        # Item 4: inherit global escalation if rule-level is None
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
    if model_proposal_tier and model_proposal_tier in profile.triage.routes and model_proposal_tier != route_tier:
        is_escalation = _is_higher_tier(model_proposal_tier, route_tier)
        if is_escalation:
            if allow_escalation:
                effective_tier = model_proposal_tier
        else:
            # De-escalation
            if allow_deescalation:
                effective_tier = model_proposal_tier

    # 3. Resolve with fallback loop for implementation status
    fallbacks_considered = []
    current_tier = effective_tier

    while True:
        if current_tier not in profile.triage.routes:
            if routing_config.strict_on_unavailable_route:
                 raise ValueError(f"Route tier {current_tier!r} not defined in profile.")
            if current_tier == routing_config.default_route:
                 raise ValueError(f"Default route tier {current_tier!r} not defined in profile.")
            fallbacks_considered.append(current_tier)
            current_tier = routing_config.default_route
            continue

        route_cfg = profile.triage.routes[current_tier]

        from code_review_loop.harnesses import harness_registry
        registry = harness_registry()
        spec = registry.get(route_cfg.harness)

        # Item 9: Deep capability validation
        if spec and spec.implemented and spec.capabilities:
            caps = spec.capabilities
            if (
                caps.remediation_supported
                and caps.non_interactive
                and route_cfg.sandbox in caps.sandbox_modes
            ):
                return ResolvedRoute(
                    route_tier=current_tier,
                    harness=route_cfg.harness,
                    model=route_cfg.model,
                    reasoning_effort=route_cfg.reasoning_effort,
                    timeout_seconds=route_cfg.timeout_seconds,
                    sandbox=route_cfg.sandbox,
                    prompt_fragments=prompt_fragments,
                    rule_id=matched_rule.id if matched_rule else "default",
                    fallbacks_considered=tuple(fallbacks_considered),
                    fallback_applied=current_tier if fallbacks_considered else None
                )

        # Item 2: Strict fallbacks - only follow explicit fallback or fail
        if not route_cfg.fallback:
            raise RuntimeError(
                f"Route {current_tier!r} (harness {route_cfg.harness!r}) is unavailable or lacks "
                f"required capabilities, and no explicit fallback is configured."
            )

        if route_cfg.fallback == current_tier:
             raise RuntimeError(f"Circular fallback detected for route {current_tier!r}.")

        fallbacks_considered.append(current_tier)
        current_tier = route_cfg.fallback


TIER_RANK = {
    "security-specialist": 200,
    "frontier": 100,
    "midtier": 50,
    "efficient": 10,
}

def _is_higher_tier(tier1: str, tier2: str) -> bool:
    # Use partial matching for well-known tier names
    rank1 = 0
    for name, rank in TIER_RANK.items():
        if name in tier1.lower():
            rank1 = rank
            break

    rank2 = 0
    for name, rank in TIER_RANK.items():
        if name in tier2.lower():
            rank2 = rank
            break

    return rank1 > rank2


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

    if cond.safety_signals_any and not any(s in cond.safety_signals_any for s in context.safety_signals):
        return False

    return not cond.failed_checks_any or any(c in cond.failed_checks_any for c in context.failed_checks)


RISK_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _risk_gte(actual: str, minimum: str) -> bool:
    return RISK_ORDER.get(actual, 1) >= RISK_ORDER.get(minimum, 1)


def _risk_lte(actual: str, maximum: str) -> bool:
    return RISK_ORDER.get(actual, 1) <= RISK_ORDER.get(maximum, 1)
