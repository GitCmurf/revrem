from __future__ import annotations

import json

import pytest

from code_review_loop import harnesses
from code_review_loop import loop as cli


@pytest.fixture
def fake_harness(monkeypatch, tmp_path):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    monkeypatch.setenv(harnesses.FAKE_HARNESS_FIXTURE_ENV, str(fixture_dir))
    return fixture_dir


def test_loop_with_v2_triage_routing(fake_harness, tmp_path, monkeypatch):
    # 1. Setup mock fixtures for fake harness
    # review_clear scenario
    clear_dir = fake_harness / "review_clear"
    clear_dir.mkdir()
    (clear_dir / "review.txt").write_text("No actionable findings.\nREVIEW_STATUS: clear\n", encoding="utf-8")

    # findings scenario
    findings_dir = fake_harness / "fake-findings"
    findings_dir.mkdir()
    (findings_dir / "review.txt").write_text("Finding: f1\nREVIEW_STATUS: findings\n", encoding="utf-8")
    # Triage v2 output
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
            "timeout_seconds": 0,
            "rationale": "proposing frontier"
        },
        "prompt_requirements": {
            "required_fragments": ["custom-principles"],
            "definition_of_done": ["DONE"],
            "triage_prompt_draft": "FIX IT"
        }
    }
    (findings_dir / "triage.txt").write_text(json.dumps(triage_payload), encoding="utf-8")

    # 2. Setup profile with routing
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README").touch()
    subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)

    (tmp_path / "custom-principles.txt").write_text("PRINCIPLES", encoding="utf-8")
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
default_route = "midtier"

[[profiles.test.triage.routing.rule]]
id = "sec"
when.domain_tags_any = ["security"]
then.route = "frontier"

[profiles.test.triage.routes.midtier]
harness = "fake"
model = "fake-clear"

[profiles.test.triage.routes.frontier]
harness = "fake"
model = "fake-clear"
timeout_seconds = 0
"""
    (tmp_path / ".revrem.toml").write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # 3. Run loop. The triage model proposes the same route tier but a
    # different model. Proposals are advisory: the configured route's model is
    # the executable decision, so the fake-clear fixture must be used.
    configured_route_dir = fake_harness / "fake-clear"
    configured_route_dir.mkdir()
    (configured_route_dir / "remediation.txt").write_text(
        "Remediation: configured route model\n", encoding="utf-8"
    )
    proposed_model_dir = fake_harness / "frontier-model"
    proposed_model_dir.mkdir()
    (proposed_model_dir / "remediation.txt").write_text(
        "Remediation: proposed model\n", encoding="utf-8"
    )

    exit_code = cli.main([
        "--profile", "test",
        "--review-model", "fake-findings",
        "--artifact-dir", "run1",
        "--max-iterations", "1",
        "--skip-final-review",
        "--trusted-repo"
    ])

    run_dir = tmp_path / "run1"
    if exit_code != 2:
        artifact = run_dir / "triage-1.txt"
        if artifact.is_file():
            print(f"FAILURE ARTIFACT: {artifact.read_text()}")
        else:
            print("FAILURE ARTIFACT NOT FOUND")
    assert exit_code == 2

    # 4. Verify artifacts
    run_dir = tmp_path / "run1"
    assert (run_dir / "triage-1.json").is_file()
    assert (run_dir / "routing-1.json").is_file()
    assert (run_dir / "remediation-1-prompt.txt").is_file()

    routing = json.loads((run_dir / "routing-1.json").read_text())
    assert routing["effective_route"]["route_tier"] == "frontier"
    assert routing["effective_route"]["model"] == "fake-clear"
    assert routing["effective_route"]["timeout_seconds"] == 0
    assert routing["model_proposal"]["model"] == "frontier-model"
    assert routing["model_proposal"]["timeout_seconds"] == 0
    assert routing["policy_decision"]["decision"] == "policy_override"
    assert routing["policy_decision"]["matched_rule_ids"] == ["sec"]
    assert (run_dir / "remediation-1.txt").read_text(encoding="utf-8") == (
        "Remediation: configured route model\n"
    )

    prompt = (run_dir / "remediation-1-prompt.txt").read_text()
    assert "PRINCIPLES" in prompt
    assert "FIX IT" in prompt
    assert "DONE" in prompt
