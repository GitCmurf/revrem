from __future__ import annotations

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
                default_route="midtier",
                rule=(
                    profiles.TriageRoutingRule(
                        id="security-rule",
                        when=profiles.TriageRoutingRuleWhen(domain_tags_any=("security",)),
                        then=profiles.TriageRoutingRuleThen(
                            route="frontier",
                            allow_model_deescalation=False
                        ),
                    ),
                ),
            ),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier": profiles.TriageRouteConfig(harness="codex", model="m2"),
                "efficient": profiles.TriageRouteConfig(harness="codex", model="m3"),
            }
        )
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
    assert resolved.route_tier == "midtier"
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
    assert resolved.route_tier == "frontier"
    assert resolved.rule_id == "security-rule"


def test_resolve_routing_model_escalation(base_profile):
    context = policy.RoutingContext(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )
    
    # Model proposes frontier (higher than midtier)
    resolved = policy.resolve_routing(base_profile, context, model_proposal_tier="frontier")
    assert resolved.route_tier == "frontier"


def test_resolve_routing_model_deescalation_forbidden(base_profile):
    context = policy.RoutingContext(
        domain_tags=("security",),
        risk_level="high",
        refactor_depth="localised",
        module_count=1,
        failed_checks=(),
        safety_signals=(),
    )
    
    # Rule matched frontier and has allow_model_deescalation=False
    # Model proposes efficient (lower)
    resolved = policy.resolve_routing(base_profile, context, model_proposal_tier="efficient")
    assert resolved.route_tier == "frontier"


def test_resolve_routing_model_deescalation_allowed(base_profile):
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier",
            ),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "efficient": profiles.TriageRouteConfig(harness="codex", model="m3"),
            }
        )
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
    resolved = policy.resolve_routing(profile, context, model_proposal_tier="efficient")
    assert resolved.route_tier == "efficient"
