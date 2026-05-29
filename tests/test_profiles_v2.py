from __future__ import annotations

import pytest

from code_review_loop import profiles


def test_parse_triage_v2_with_routing(tmp_path):
    toml = """
[profiles.test.triage]
contract = "v2"
enabled = true

[profiles.test.triage.routing]
enabled = true
default_route = "midtier-coder"

[[profiles.test.triage.routing.rule]]
id = "security"
when.domain_tags_any = ["security"]
then.route = "frontier-thinking"

[profiles.test.triage.routes.frontier-thinking]
harness = "codex"
model = "gpt-4-security"
timeout_seconds = 1800

[profiles.test.triage.routes.midtier-coder]
harness = "codex"
model = "gpt-3.5-turbo"
"""
    path = tmp_path / "profiles.toml"
    path.write_text(toml, encoding="utf-8")

    profile_file = profiles.load_profile_file(path)
    profile = profile_file.profiles["test"]

    assert profile.triage.contract == "v2"
    assert profile.triage.routing.enabled is True
    assert profile.triage.routing.default_route == "midtier-coder"
    assert len(profile.triage.routing.rule) == 1
    assert profile.triage.routing.rule[0].id == "security"
    assert profile.triage.routing.rule[0].when.domain_tags_any == ("security",)
    assert profile.triage.routing.rule[0].then.route == "frontier-thinking"
    assert profile.triage.routes["frontier-thinking"].model == "gpt-4-security"


def test_validate_routing_errors(tmp_path):
    # Routing enabled but contract is v1
    toml = """
[profiles.test.triage]
contract = "v1"
routing.enabled = true
"""
    path = tmp_path / "profiles.toml"
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(ValueError, match="triage.routing.enabled requires triage.contract = 'v2'"):
        profiles.load_profile_file(path)

    # Unknown route in rule
    toml = """
[profiles.test.triage]
contract = "v2"
routing.enabled = true
[[profiles.test.triage.routing.rule]]
id = "test"
then.route = "missing"
"""
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(ValueError, match="then.route refers to unknown route: missing"):
        profiles.load_profile_file(path)


def test_parse_triage_routing_rule_rejects_unknown_risk_and_refactor_values(tmp_path):
    path = tmp_path / "profiles.toml"

    path.write_text(
        """
[profiles.test.triage]
contract = "v2"
routing.enabled = true

[[profiles.test.triage.routing.rule]]
id = "bad-risk"
when.risk_level_min = "urgent"
then.route = "midtier"

[profiles.test.triage.routes.midtier]
harness = "codex"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="risk_level_min must be one of"):
        profiles.load_profile_file(path)

    path.write_text(
        """
[profiles.test.triage]
contract = "v2"
routing.enabled = true

[[profiles.test.triage.routing.rule]]
id = "bad-refactor"
when.refactor_depth_any = ["wide"]
then.route = "midtier"

[profiles.test.triage.routes.midtier]
harness = "codex"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="refactor_depth_any must contain only"):
        profiles.load_profile_file(path)


def test_validate_profile_rejects_circular_route_fallback_chain():
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

    with pytest.raises(ValueError, match="circular fallback chain"):
        profiles.validate_profile(profile, require_implemented=True)


def test_resolve_profile_allows_disabled_routing_with_unimplemented_route_chain(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.draft.triage]
enabled = true

[profiles.draft.triage.routing]
enabled = false

[profiles.draft.triage.routes.frontier]
harness = "reserved"
fallback = "midtier"

[profiles.draft.triage.routes.midtier]
harness = "reserved"
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile("draft", cwd=cwd, home=home)

    assert resolved.triage.routing.enabled is False
    assert tuple(resolved.triage.routes) == ("frontier", "midtier")


def test_to_toml_preserves_routing(tmp_path):
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                rule=(
                    profiles.TriageRoutingRule(
                        id="r1",
                        when=profiles.TriageRoutingRuleWhen(domain_tags_any=("a",)),
                        then=profiles.TriageRoutingRuleThen(route="f"),
                    ),
                ),
            ),
            routes={
                "f": profiles.TriageRouteConfig(model="m")
            }
        )
    )

    toml_str = profiles.profile_to_toml(profile)
    assert 'contract = "v2"' in toml_str
    assert '[triage.routing]' in toml_str
    assert 'enabled = true' in toml_str
    assert 'id = "r1"' in toml_str
    assert 'domain_tags_any = ["a"]' in toml_str
    assert 'route = "f"' in toml_str
    assert '[triage.routes.f]' in toml_str
    assert 'model = "m"' in toml_str
