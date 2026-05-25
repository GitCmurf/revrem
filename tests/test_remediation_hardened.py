from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from code_review_loop import harnesses, policy, prompts_composer
from code_review_loop import loop as cli
from code_review_loop._compat_jsonschema import validate
from code_review_loop.cli.main import main as cli_main


@pytest.fixture
def fake_harness(monkeypatch, tmp_path):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    monkeypatch.setenv(harnesses.FAKE_HARNESS_FIXTURE_ENV, str(fixture_dir))
    return fixture_dir

def test_loop_generates_schema_compliant_routing_artifact(fake_harness, tmp_path, monkeypatch):
    # Setup mock fixtures
    findings_dir = fake_harness / "fake-findings"
    findings_dir.mkdir()
    (findings_dir / "review.txt").write_text("Finding: f1\nREVIEW_STATUS: findings\n", encoding="utf-8")

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

    # Init git repo for preflight
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
"""
    (tmp_path / ".revrem.toml").write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main(["--profile", "test", "--review-model", "fake-findings", "--max-iterations", "1", "--skip-final-review", "--trusted-repo"])
    assert exit_code == 2

    routing_path = tmp_path / ".revrem/runs"
    run_dir = next(routing_path.iterdir())
    routing_file = run_dir / "routing-1.json"
    assert routing_file.is_file()

    routing_data = json.loads(routing_file.read_text())
    schema = json.loads(files("code_review_loop").joinpath("schemas/routing-v1.schema.json").read_text(encoding="utf-8"))
    validate(routing_data, schema)

def test_build_remediation_command_uses_harness_executable(monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    config = cli.LoopConfig(
        codex_bin="custom-codex",
        remediation_harness="codex",
        artifact_dir=Path("/tmp"),
        base="main",
        max_iterations=1,
        cwd=Path("/tmp")
    )
    # Default (Codex)
    cmd = cli.build_remediation_command(config)
    assert cmd[0] == "custom-codex"

    # Routed to fake
    resolved = policy.ResolvedRoute(
        route_tier="f", harness="fake", model="m", reasoning_effort="l", timeout_seconds=1,
        sandbox="s", prompt_fragments=(), allow_model_deescalation=True
    )
    cmd = cli.build_remediation_command(config, resolved_route=resolved)
    assert cmd[0] == harnesses.FAKE_HARNESS_COMMAND

def test_deterministic_safety_signal_escalation():
    profile = cli.profiles.Profile(
        name="test",
        triage=cli.profiles.TriageConfig(
            contract="v2",
            routing=cli.profiles.TriageRoutingConfig(
                enabled=True,
                rule=(cli.profiles.TriageRoutingRule(
                    id="sec",
                    when=cli.profiles.TriageRoutingRuleWhen(safety_signals_any=("sensitive-domain:auth",)),
                    then=cli.profiles.TriageRoutingRuleThen(route="high-tier")
                ),),
                default_route="low-tier"
            ),
            routes={
                "low-tier": cli.profiles.TriageRouteConfig(harness="codex"),
                "high-tier": cli.profiles.TriageRouteConfig(harness="codex")
            }
        )
    )
    context = policy.RoutingContext(
        domain_tags=(), risk_level="low", refactor_depth="atomic", module_count=1,
        failed_checks=(), safety_signals=("sensitive-domain:auth",)
    )
    resolved = policy.resolve_routing(profile, context)
    assert resolved.route_tier == "high-tier"

def test_prompt_safety_truncation_protection(tmp_path):
    triage_payload = {
        "classification": {"risk_level": "critical", "refactor_depth": "architectural"},
        "prompt_requirements": {"definition_of_done": ["MUST_NOT_BE_TRUNCATED"]}
    }
    resolved = policy.ResolvedRoute(
        route_tier="f", harness="h", model="m", reasoning_effort="h", timeout_seconds=1,
        sandbox="s", prompt_fragments=(), allow_model_deescalation=False, rule_id="sec-rule"
    )
    original_review = "REALLY_LONG_REVIEW" * 1000

    # Header should remain. Review should be truncated.
    prompt = prompts_composer.compose_remediation_prompt(
        tmp_path, triage_payload, resolved, original_review, max_chars=1000
    )
    assert "MUST_NOT_BE_TRUNCATED" in prompt
    assert "sec-rule" in prompt
    assert "[... omitted" in prompt
    assert len(prompt) <= 1000

    # If limit is too small for header, it must fail
    with pytest.raises(ValueError, match="mandatory prompt header"):
        prompts_composer.compose_remediation_prompt(
            tmp_path, triage_payload, resolved, original_review, max_chars=100
        )
