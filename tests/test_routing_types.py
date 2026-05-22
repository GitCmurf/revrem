"""Smoke tests for core/routing_types.py (REVREM-TASK-003 B1b).

Verifies that the pure DTOs are importable from their new home in core/ and
that profiles.py re-exports them unchanged (backward compat).
"""

from __future__ import annotations


def test_routing_types_importable_from_core() -> None:
    from code_review_loop.core.routing_types import (
        Profile,
        TriageConfig,
        TriageRouteConfig,
        TriageRoutingConfig,
        TriageRoutingRule,
    )

    # Smoke test that the core module works standalone
    r = TriageRouteConfig(harness="codex")
    assert r.harness == "codex"

    rc = TriageRoutingConfig()
    assert rc.enabled is False
    assert rc.default_route == "midtier-coder"

    p = Profile(name="test")
    assert p.name == "test"
    assert isinstance(p.triage, TriageConfig)

    _ = TriageRoutingRule  # just confirm importable


def test_commit_on_hook_failure_choices_in_core() -> None:
    from code_review_loop.core.routing_types import COMMIT_ON_HOOK_FAILURE_CHOICES

    assert "remediate" in COMMIT_ON_HOOK_FAILURE_CHOICES
    assert "stop" in COMMIT_ON_HOOK_FAILURE_CHOICES
    assert "no-verify" in COMMIT_ON_HOOK_FAILURE_CHOICES


def test_profiles_re_exports_routing_types() -> None:
    """profiles.py must still export all DTOs for backward compat."""
    import code_review_loop.profiles as profiles
    from code_review_loop.core.routing_types import (
        BudgetConfig,
        CommitConfig,
        OutputConfig,
        PhaseConfig,
        PipelineConfig,
        Profile,
        ProfileFile,
        ProfileListItem,
        RuntimeConfig,
        SuppressionsConfig,
        TriageConfig,
        TriageRouteConfig,
        TriageRoutingConfig,
        TriageRoutingRule,
        TriageRoutingRuleThen,
        TriageRoutingRuleWhen,
    )

    assert profiles.Profile is Profile
    assert profiles.PhaseConfig is PhaseConfig
    assert profiles.TriageRouteConfig is TriageRouteConfig
    assert profiles.TriageRoutingRule is TriageRoutingRule
    assert profiles.TriageRoutingRuleWhen is TriageRoutingRuleWhen
    assert profiles.TriageRoutingRuleThen is TriageRoutingRuleThen
    assert profiles.TriageRoutingConfig is TriageRoutingConfig
    assert profiles.TriageConfig is TriageConfig
    assert profiles.PipelineConfig is PipelineConfig
    assert profiles.CommitConfig is CommitConfig
    assert profiles.OutputConfig is OutputConfig
    assert profiles.RuntimeConfig is RuntimeConfig
    assert profiles.BudgetConfig is BudgetConfig
    assert profiles.SuppressionsConfig is SuppressionsConfig
    assert profiles.ProfileFile is ProfileFile
    assert profiles.ProfileListItem is ProfileListItem


def test_policy_reexports_resolved_route() -> None:
    """policy.py must re-export ResolvedRoute from its new core home."""
    import code_review_loop.policy as policy
    from code_review_loop.core.routing_types import ResolvedRoute

    assert policy.ResolvedRoute is ResolvedRoute
