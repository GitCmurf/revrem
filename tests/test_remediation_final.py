from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from code_review_loop import harnesses, policy, profiles, prompts_composer, triage
from code_review_loop._compat_jsonschema import validate
from code_review_loop.cli.main import main as cli_main
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from tests.support import application_runner


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
    # Setup profile where 'frontier-thinking' uses an unimplemented harness but
    # has a fallback to 'midtier-coder'
    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="midtier-coder",
                strict_on_unavailable_route=False,
            ),
            routes={
                "midtier-coder": profiles.TriageRouteConfig(harness="codex", model="fake-clear"),
                "frontier-thinking": profiles.TriageRouteConfig(harness="reserved", model="fake-clear", fallback="midtier-coder")
            }
        )
    )

    context = policy.RoutingContext(
        domain_tags=(), risk_level="low", refactor_depth="atomic", module_count=1,
        failed_checks=(), safety_signals=()
    )

    # Model proposes frontier-thinking (reserved - unimplemented)
    resolved = policy.resolve_routing(profile, context, model_proposal_tier="frontier-thinking")

    assert resolved.route_tier == "midtier-coder"
    assert resolved.fallback_applied == "midtier-coder"
    assert resolved.fallbacks_considered == ("frontier-thinking",)
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
    (findings_dir / "review.txt").write_text("Finding: f1\nREVIEW_STATUS: findings\n", encoding="utf-8")

    triage_payload = {
        "confirmed_findings": [{"fingerprint": "f1", "summary": "s", "severity": "P2", "affected_paths": ["a.py"], "rationale": "r"}],
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
            "route_tier": "frontier-thinking",
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
default_route = "midtier-coder"
[profiles.test.triage.routes.midtier-coder]
harness = "fake"
[profiles.test.triage.routes.frontier-thinking]
harness = "fake"
model = "fake-clear"
reasoning_effort = "high"
"""
    (tmp_path / ".revrem.toml").write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Run loop
    exit_code = cli_main(["--profile", "test", "--review-model", "fake-findings", "--max-iterations", "1", "--skip-final-review", "--trusted-repo"])
    assert exit_code == 2

    # 1. Validate routing artifact
    routing_path = tmp_path / ".revrem/runs"
    run_dir = next(routing_path.iterdir())
    routing_file = run_dir / "routing-1.json"
    assert routing_file.is_file()
    triage_data = json.loads((run_dir / "triage-1.json").read_text())
    assert triage_data["confirmed_findings"][0]["severity"] == "medium"
    assert any("P2" in warning for warning in triage_data["parsing_warnings"])

    routing_data = json.loads(routing_file.read_text())
    routing_schema = json.loads(files("code_review_loop").joinpath("schemas/routing-v1.schema.json").read_text(encoding="utf-8"))
    validate(routing_data, routing_schema)
    assert routing_data["model_proposal"]["model"] == "frontier-model"
    assert routing_data["model_proposal"]["reasoning_effort"] == "high"
    assert routing_data["model_proposal"]["sandbox"] == "workspace-write"
    assert routing_data["model_proposal"]["timeout_seconds"] == 60
    assert routing_data["policy_decision"]["decision"] == "policy_override"
    assert "model" in routing_data["policy_decision"]["rationale"]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert any(path.endswith("remediation-1-prompt.txt") for path in summary["artifact_paths"]["prompts"])
    assert any(path.endswith("routing-1.json") for path in summary["artifact_paths"]["routing"])
    assert any(path.endswith("routing-outcome-1.json") for path in summary["artifact_paths"]["routing"])

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


def test_routed_remediation_prompt_preserves_pending_check_failures(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    review_outputs = iter(
        [
            "Initial finding.\nREVIEW_STATUS: findings\n",
            "Review clear but checks failed previously.\nREVIEW_STATUS: clear\n",
        ]
    )
    check_outputs = iter(
        [
            (1, "FAILED tests/test_example.py::test_previous\n"),
            (0, "passed\n"),
        ]
    )
    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1",
                "summary": "s",
                "severity": "high",
                "affected_paths": ["a.py"],
                "rationale": "r",
            }
        ],
        "rejected_findings": [],
        "needs_more_info": [],
        "implementation_order": ["f1"],
        "verification_commands": [],
        "parsing_warnings": [],
        "classification": {
            "domain_tags": ["tests"],
            "risk_level": "low",
            "refactor_depth": "atomic",
            "affected_modules": ["a.py"],
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": [],
            "failed_check_signals": [],
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": ["checks pass"],
            "triage_prompt_draft": "Fix the finding.",
        },
    }

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[0] == "revrem-fake-harness" and args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "revrem-fake-harness" and args[1] == "triage":
            return CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        if args[0] == "revrem-fake-harness" and args[1] == "remediation":
            return CommandResult(list(args), 0, stdout="remediated\n")
        if args[0] == "pytest":
            returncode, stdout = next(check_outputs)
            return CommandResult(list(args), returncode, stdout=stdout)
        raise AssertionError(f"unexpected command: {args}")

    profile = profiles.Profile(
        name="test",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(enabled=True, default_route="midtier"),
            routes={
                "midtier": profiles.TriageRouteConfig(harness="fake", model="fake-clear")
            },
        ),
    )
    config = LoopConfig(
        base="main",
        max_iterations=2,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="review_findings",
        triage_enabled=True,
        triage_contract="v2",
        triage_harness="fake",
        triage_model="triage_valid",
        remediation_harness="fake",
        check_commands=("pytest tests/",),
        final_review=False,
        profile_v2=profile,
    )

    summary = application_runner.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "unknown"
    prompt = (tmp_path / "artifacts" / "remediation-2-prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "FAILED tests/test_example.py::test_previous" in prompt
