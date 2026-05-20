import pytest
from code_review_loop import profiles

def test_validate_policy_handles_unknown_fallback_without_keyerror():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(enabled=True, default_route="midtier"),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="m1", fallback="missing")
            }
        )
    )
    # This should not raise KeyError
    issues = profiles.validate_policy(profile)
    assert any("route 'midtier' has unknown fallback: 'missing'" in i for i in issues)
