"""Regression tests for the B1-B3 routing blockers.

These exercise the routing layer with the *canonical* tier vocabulary that the
product actually ships (frontier-thinking / midtier-coder / efficient-coder /
security-specialist) and the orchestrator-enforced timeout contract, which the
original test suite never covered.
"""

from __future__ import annotations

import pytest

from code_review_loop import policy, profiles, prompts_composer


def _ctx(**overrides):
    base = dict(
        domain_tags=("docs",),
        risk_level="low",
        refactor_depth="atomic",
        module_count=1,
        safety_signals=(),
        failed_checks=(),
    )
    base.update(overrides)
    return policy.RoutingContext(**base)


# --- B1: orchestrator-enforced timeouts -------------------------------------


def test_resolve_routing_allows_external_timeout_on_non_codex_harness():
    # RevRem enforces timeouts via its own subprocess wrapper, so a route to a
    # harness whose CLI lacks a native timeout flag must still be selectable.
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True, default_route="frontier-thinking"
            ),
            routes={
                "frontier-thinking": profiles.TriageRouteConfig(
                    harness="claude",
                    model="sonnet",
                    timeout_seconds=1800,
                    sandbox="workspace-write",
                ),
            },
        ),
    )
    resolved = policy.resolve_routing(profile, _ctx())
    assert resolved.harness == "claude"
    assert resolved.timeout_seconds == 1800


def test_check_route_capabilities_accepts_timeout_on_non_codex():
    route = profiles.TriageRouteConfig(
        harness="gemini", model="g", timeout_seconds=900, sandbox="workspace-write"
    )
    assert policy.check_route_capabilities(route) == []


# --- B2: canonical tier vocabulary + escalation gating ----------------------


def test_resolve_routing_model_escalation_canonical_tier_names():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True, default_route="midtier-coder"
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier-thinking": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )
    resolved = policy.resolve_routing(
        profile, _ctx(), model_proposal_tier="frontier-thinking"
    )
    assert resolved.route_tier == "frontier-thinking"


def test_resolve_routing_security_specialist_outranks_default():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True, default_route="midtier-coder"
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "security-specialist": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )
    resolved = policy.resolve_routing(
        profile, _ctx(), model_proposal_tier="security-specialist"
    )
    assert resolved.route_tier == "security-specialist"


def test_resolve_routing_escalation_blocked_when_disallowed():
    # A genuine upward proposal must be gated by allow_model_escalation, not
    # silently applied through the de-escalation branch.
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
                allow_model_escalation=False,
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier-thinking": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )
    resolved = policy.resolve_routing(
        profile, _ctx(), model_proposal_tier="frontier-thinking"
    )
    assert resolved.route_tier == "midtier-coder"


def test_resolve_routing_indeterminate_tier_keeps_policy_route():
    # If the model proposes a tier whose rank can't be compared to the policy
    # route, policy must win rather than silently applying the proposal.
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True, default_route="midtier-coder"
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "house-special": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )
    resolved = policy.resolve_routing(
        profile, _ctx(), model_proposal_tier="house-special"
    )
    assert resolved.route_tier == "midtier-coder"


# --- M1: deterministic safety backstop reaches domain_tags_any rules --------


def test_deterministic_detection_escalates_domain_tags_any_rule(tmp_path):
    # Mirrors the documented `secure` profile: a domain_tags_any security rule
    # must escalate even when the model omits the security tag, because the
    # finding's file content deterministically reveals a sensitive domain.
    from code_review_loop import triage

    auth_py = tmp_path / "auth.py"
    auth_py.write_text("def login(user, password): ...", encoding="utf-8")

    profile = profiles.Profile(
        name="secure",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
                rule=(
                    profiles.TriageRoutingRule(
                        id="security-frontier",
                        when=profiles.TriageRoutingRuleWhen(
                            domain_tags_any=("security", "auth", "secrets", "pii")
                        ),
                        then=profiles.TriageRoutingRuleThen(
                            route="frontier-thinking", allow_model_deescalation=False
                        ),
                    ),
                ),
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="m1"),
                "frontier-thinking": profiles.TriageRouteConfig(harness="codex", model="m2"),
            },
        ),
    )

    payload = {
        "confirmed_findings": [
            {"affected_paths": ["auth.py"], "fingerprint": "f1", "summary": "s", "severity": "high", "rationale": "r"}
        ],
        "classification": {
            "domain_tags": ["docs"],  # model omits any security tag
            "risk_level": "low",
            "refactor_depth": "atomic",
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
        },
    }

    context = triage.extract_routing_context(payload, tmp_path)
    resolved = policy.resolve_routing(profile, context)
    assert resolved.route_tier == "frontier-thinking"
    assert resolved.rule_id == "security-frontier"


# --- B3: built-in prompt fragments ------------------------------------------

CANONICAL_FRAGMENTS = [
    "engineering-principles",
    "security-checklist",
    "architecture-checklist",
    "definition-of-done",
    "regression-test-checklist",
    "atomic-task-list",
]


@pytest.mark.parametrize("name", CANONICAL_FRAGMENTS)
def test_builtin_fragment_resolves(tmp_path, name):
    content = prompts_composer.load_fragment(tmp_path, name)
    assert content, f"built-in fragment {name!r} should resolve to non-empty text"


def test_compose_prompt_includes_requested_builtin_fragments(tmp_path):
    resolved = policy.ResolvedRoute(
        route_tier="security-specialist",
        harness="codex",
        prompt_fragments=("engineering-principles", "security-checklist"),
    )
    prompt = prompts_composer.compose_remediation_prompt(
        cwd=tmp_path,
        triage_payload={"classification": {}, "prompt_requirements": {}},
        resolved_route=resolved,
        original_review="review text",
    )
    assert "Fragment: security-checklist" in prompt
