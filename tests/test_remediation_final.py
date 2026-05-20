from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from code_review_loop import cli, harnesses, policy, profiles, prompts_composer, triage
from code_review_loop._compat_jsonschema import validate


@pytest.fixture
def fake_harness(monkeypatch, tmp_path):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    monkeypatch.setenv(harnesses.FAKE_HARNESS_FIXTURE_ENV, str(fixture_dir))
    return fixture_dir

def test_invalid_triage_contract_is_rejected():
    with pytest.raises(ValueError, match="invalid triage contract version"):
        triage.load_prompt("bogus")

    with pytest.raises(ValueError, match="invalid triage contract version"):
        triage.parse_triage_payload("{}", run_id="r", source_review_artifact="s", contract="bogus")

def test_fallback_behavior_for_unimplemented_harness():
    # Setup profile where 'frontier' uses an unimplemented harness but has a fallback to 'midtier'
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(enabled=True, default_route="midtier"),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex", model="fake-clear"),
                "frontier": profiles.TriageRouteConfig(harness="reserved", model="fake-clear", fallback="midtier")
            }
        )
    )

    context = policy.RoutingContext(
        domain_tags=(), risk_level="low", refactor_depth="atomic", module_count=1,
        failed_checks=(), safety_signals=()
    )

    # Model proposes frontier (claude - unimplemented)
    resolved = policy.resolve_routing(profile, context, model_proposal_tier="frontier")

    assert resolved.route_tier == "midtier"
    assert resolved.fallback_applied == "midtier"
    assert resolved.fallbacks_considered == ("frontier",)
    assert resolved.harness == "codex"

def test_failed_checks_any_matches_exact_command():
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                rule=(profiles.TriageRoutingRule(
                    id="precise-rule",
                    when=profiles.TriageRoutingRuleWhen(failed_checks_any=("pytest -q tests/foo.py",)),
                    then=profiles.TriageRoutingRuleThen(route="frontier")
                ),),
                default_route="midtier"
            ),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="codex"),
                "frontier": profiles.TriageRouteConfig(harness="codex")
            }
        )
    )

    # Match
    context = policy.RoutingContext(
        domain_tags=(), risk_level="low", refactor_depth="atomic", module_count=1,
        failed_checks=("pytest -q tests/foo.py",), safety_signals=()
    )
    resolved = policy.resolve_routing(profile, context)
    assert resolved.route_tier == "frontier"

    # No match on executable only
    context_lossy = policy.RoutingContext(
        domain_tags=(), risk_level="low", refactor_depth="atomic", module_count=1,
        failed_checks=("pytest",), safety_signals=()
    )
    resolved_lossy = policy.resolve_routing(profile, context_lossy)
    assert resolved_lossy.route_tier == "midtier"

def test_missing_prompt_fragment_fails_routing(tmp_path):
    triage_payload = {
        "classification": {"risk_level": "low", "refactor_depth": "atomic"},
        "prompt_requirements": {"required_fragments": ["missing-fragment"]}
    }
    resolved = policy.ResolvedRoute(
        route_tier="f", harness="h", model="m", reasoning_effort="l", timeout_seconds=1,
        sandbox="s", prompt_fragments=(), allow_model_deescalation=True
    )

    with pytest.raises(ValueError, match="could not be resolved or is untrusted"):
        prompts_composer.compose_remediation_prompt(
            tmp_path, triage_payload, resolved, "rev"
        )

def test_routing_artifact_and_events_validate_against_schemas(fake_harness, tmp_path, monkeypatch):
    # Setup mock fixtures
    findings_dir = fake_harness / "fake-findings"
    findings_dir.mkdir()
    (findings_dir / "review.txt").write_text("Findings: f1", encoding="utf-8")

    triage_payload = {
        "confirmed_findings": [{"fingerprint": "f1", "summary": "s", "severity": "high", "affected_paths": ["a.py"], "rationale": "r"}],
        "rejected_findings": [],
        "needs_more_info": [],
        "implementation_order": ["f1"],
        "verification_commands": [],
        "parsing_warnings": [],
        "classification": {
            "domain_tags": ["security"],
            "risk_level": "high",
            "refactor_depth": "atomic",
            "affected_modules": ["auth"],
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": [],
            "failed_check_signals": []
        },
        "route_proposal": {
            "route_tier": "frontier",
            "harness": "fake",
            "model": "frontier-model",
            "reasoning_effort": "high",
            "sandbox": "workspace-write",
            "timeout_seconds": 60,
            "rationale": "proposing frontier"
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": ["DONE"],
            "triage_prompt_draft": "FIX IT"
        }
    }
    (findings_dir / "triage.txt").write_text(json.dumps(triage_payload), encoding="utf-8")

    # Provide remediation fixture for frontier-model
    frontier_dir = fake_harness / "fake-clear"
    frontier_dir.mkdir()
    (frontier_dir / "remediation.txt").write_text("Remediation: done", encoding="utf-8")

    # Setup profile
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README").touch()
    subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=tmp_path, check=True)

    toml = """
[profiles.test.review]
harness = "fake"
[profiles.test.remediation]
harness = "fake"
[profiles.test.triage]
contract = "v2"
enabled = true
harness = "fake"
model = "fake-findings"
[profiles.test.triage.routing]
enabled = true
default_route = "m"
[profiles.test.triage.routes.m]
harness = "fake"
[profiles.test.triage.routes.frontier]
harness = "fake"
model = "fake-clear"
reasoning_effort = "high"
"""
    (tmp_path / ".revrem.toml").write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Run loop
    exit_code = cli.main(["--profile", "test", "--review-model", "fake-findings", "--max-iterations", "1", "--skip-final-review", "--trusted-repo"])
    assert exit_code in (0, 2)

    # 1. Validate routing artifact
    routing_path = tmp_path / ".revrem/runs"
    run_dir = next(routing_path.iterdir())
    routing_file = run_dir / "routing-1.json"
    assert routing_file.is_file()

    routing_data = json.loads(routing_file.read_text())
    routing_schema = json.loads(files("code_review_loop").joinpath("schemas/routing-v1.schema.json").read_text(encoding="utf-8"))
    validate(routing_data, routing_schema)

    # 2. Validate routing outcome artifact
    outcome_file = run_dir / "routing-outcome-1.json"
    assert outcome_file.is_file()
    outcome_data = json.loads(outcome_file.read_text())
    outcome_schema = json.loads(files("code_review_loop").joinpath("schemas/routing-outcome-v1.schema.json").read_text(encoding="utf-8"))
    validate(outcome_data, outcome_schema)

    # 3. Validate events stream
    events_file = run_dir / "events.jsonl"
    assert events_file.is_file()
    events_schema = json.loads((Path(__file__).resolve().parents[1] / "docs/52-api/schemas/events-v1.schema.json").read_text(encoding="utf-8"))

    has_decision = False
    has_outcome = False
    with events_file.open("r", encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            validate(event, events_schema)
            if event["kind"] == "routing_decision":
                has_decision = True
            if event["kind"] == "routing_outcome":
                has_outcome = True

    assert has_decision
    assert has_outcome
