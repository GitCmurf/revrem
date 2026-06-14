from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import policy, profiles


@pytest.fixture
def base_profile():
    return profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
                rule=(
                    profiles.TriageRoutingRule(
                        id="security-rule",
                        when=profiles.TriageRoutingRuleWhen(domain_tags_any=("security",)),
                        then=profiles.TriageRoutingRuleThen(
                            route="frontier-thinking", allow_model_deescalation=False
                        ),
                    ),
                ),
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier-thinking": profiles.TriageRouteConfig(harness="codex", model="m2"),
                "efficient-coder": profiles.TriageRouteConfig(harness="codex", model="m3"),
            },
        ),
    )


def test_resolve_routing_default(base_profile):
    context = policy.RoutingContext(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(base_profile, context)
    assert resolved.route_tier == "midtier-coder"
    assert resolved.rule_id == "default"


def test_resolve_routing_rule_match(base_profile):
    context = policy.RoutingContext(
        domain_tags=("security",),
        risk_level="high",
        refactor_depth="localised",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(base_profile, context)
    assert resolved.route_tier == "frontier-thinking"
    assert resolved.rule_id == "security-rule"


def test_project_dogfood_profile_routes_multi_file_changes_to_gemini():
    loaded = profiles.load_profile_file(Path(profiles.PROJECT_CONFIG_NAME))
    profile = loaded.profiles["dogfood"]
    context = policy.RoutingContext(
        domain_tags=("python",),
        risk_level="medium",
        refactor_depth="localised",
        module_count=4,
        failed_checks=(),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(profile, context)

    assert resolved.route_tier == "gemini-pro"
    assert resolved.harness == "gemini"
    assert resolved.model == "gemini-3.1-pro-preview"
    assert resolved.fallback_applied is None


def test_project_default_profile_has_routing_fallbacks_when_enabled():
    loaded = profiles.load_profile_file(Path(profiles.PROJECT_CONFIG_NAME))
    profile = loaded.profiles["default"]
    context = policy.RoutingContext(
        domain_tags=("python",),
        risk_level="medium",
        refactor_depth="localised",
        module_count=4,
        failed_checks=(),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(profile, context)

    assert resolved.route_tier in {"gemini-pro", "codex-midi"}
    if resolved.route_tier == "codex-midi":
        assert resolved.fallback_applied == "codex-midi"
        assert resolved.fallbacks_considered == ("gemini-pro",)


def test_resolve_routing_model_escalation():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier-thinking": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    # Model proposes frontier-thinking (higher than midtier-coder)
    resolved = policy.resolve_routing(profile, context, model_proposal_tier="frontier-thinking")
    assert resolved.route_tier == "frontier-thinking"


def test_resolve_routing_model_deescalation_forbidden(base_profile):
    context = policy.RoutingContext(
        domain_tags=("security",),
        risk_level="high",
        refactor_depth="localised",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    # Rule matched frontier-thinking and has allow_model_deescalation=False
    # Model proposes efficient-coder (lower)
    resolved = policy.resolve_routing(base_profile, context, model_proposal_tier="efficient-coder")
    assert resolved.route_tier == "frontier-thinking"


def test_resolve_routing_model_deescalation_allowed(base_profile):
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "efficient-coder": profiles.TriageRouteConfig(harness="codex", model="m3"),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    # Default route allows de-escalation by default (allow_model_deescalation=True)
    resolved = policy.resolve_routing(profile, context, model_proposal_tier="efficient-coder")
    assert resolved.route_tier == "efficient-coder"


def test_resolve_routing_rejects_multi_hop_fallback_cycle():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="frontier",
                strict_on_unavailable_route=False,
            ),
            routes={
                "frontier": profiles.TriageRouteConfig(
                    harness="reserved",
                    fallback="midtier",
                ),
                "midtier": profiles.TriageRouteConfig(
                    harness="reserved",
                    fallback="frontier",
                ),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=(),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    with pytest.raises(RuntimeError, match="Circular fallback detected"):
        policy.resolve_routing(profile, context)


def test_trivial_risk_does_not_match_low_minimum(base_profile):
    rule = profiles.TriageRoutingRule(
        id="low-risk",
        when=profiles.TriageRoutingRuleWhen(risk_level_min="low"),
        then=profiles.TriageRoutingRuleThen(route="frontier"),
    )
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier",
                rule=(rule,),
            ),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=(),
        risk_level="trivial",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(profile, context)
    assert resolved.route_tier == "midtier"


def test_resolve_routing_uses_explicit_fallback_when_route_exceeds_wall_budget():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="frontier",
                strict_on_unavailable_route=False,
            ),
            routes={
                "frontier": profiles.TriageRouteConfig(
                    harness="codex",
                    model="m1",
                    timeout_seconds=1800,
                    fallback="efficient",
                ),
                "efficient": profiles.TriageRouteConfig(
                    harness="codex",
                    model="m2",
                    timeout_seconds=120,
                ),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=(),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(profile, context, max_timeout_seconds=300)

    assert resolved.route_tier == "efficient"
    assert resolved.fallback_applied == "efficient"
    assert resolved.fallbacks_considered == ("frontier",)


def test_resolve_routing_strict_mode_rejects_unavailable_route_with_fallback():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
                strict_on_unavailable_route=True,
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier-thinking": profiles.TriageRouteConfig(
                    harness="reserved",
                    model="m2",
                    fallback="midtier-coder",
                ),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=(),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    with pytest.raises(RuntimeError, match="strict routing is enabled"):
        policy.resolve_routing(profile, context, model_proposal_tier="frontier-thinking")


def test_resolve_routing_fails_when_budget_exceeded_route_has_no_fallback():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="frontier",
            ),
            routes={
                "frontier": profiles.TriageRouteConfig(
                    harness="codex",
                    model="m1",
                    timeout_seconds=1800,
                ),
            },
        ),
    )
    context = policy.RoutingContext(
        domain_tags=(),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )

    with pytest.raises(RuntimeError, match="remaining wall budget"):
        policy.resolve_routing(profile, context, max_timeout_seconds=300)
