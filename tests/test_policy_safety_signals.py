from __future__ import annotations

from code_review_loop import policy, profiles


def test_deterministic_safety_signal_triggers_security_routing():
    # Setup profile with a rule that matches a specific safety signal
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier",
                rule=(
                    profiles.TriageRoutingRule(
                        id="security-policy",
                        when=profiles.TriageRoutingRuleWhen(
                            safety_signals_any=("sensitive-domain:auth",)
                        ),
                        then=profiles.TriageRoutingRuleThen(route="frontier"),
                    ),
                ),
            ),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )

    # Context with no security domain tags, but a deterministic safety signal
    context = policy.RoutingContext(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=(),
        safety_signals=("sensitive-domain:auth",),
    )

    resolved = policy.resolve_routing(profile, context)
    assert resolved.route_tier == "frontier"
    assert resolved.rule_id == "security-policy"


def test_failed_check_triggers_routing():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier",
                rule=(
                    profiles.TriageRoutingRule(
                        id="test-failure-policy",
                        when=profiles.TriageRoutingRuleWhen(failed_checks_any=("pytest",)),
                        then=profiles.TriageRoutingRuleThen(route="frontier"),
                    ),
                ),
            ),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )

    context = policy.RoutingContext(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        failed_checks=("pytest",),
        safety_signals=(),
    )

    resolved = policy.resolve_routing(profile, context)
    assert resolved.route_tier == "frontier"
    assert resolved.rule_id == "test-failure-policy"
