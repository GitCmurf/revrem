from __future__ import annotations

import tomllib
from pathlib import Path

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
