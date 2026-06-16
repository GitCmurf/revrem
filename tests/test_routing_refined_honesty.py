from __future__ import annotations

import json
import subprocess

import pytest

from code_review_loop import harnesses
from code_review_loop.cli.main import main as cli_main


@pytest.fixture
def fake_harness(monkeypatch, tmp_path):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    monkeypatch.setenv(harnesses.FAKE_HARNESS_FIXTURE_ENV, str(fixture_dir))
    return fixture_dir


def _init_git_repo(path):
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README").touch()
    subprocess.run(["git", "add", "README"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True)


def test_default_route_artifact_honesty_uses_production_loop(fake_harness, tmp_path, monkeypatch):
    findings_dir = fake_harness / "fake-findings"
    findings_dir.mkdir()
    (findings_dir / "review.txt").write_text(
        "Finding: f1\nREVIEW_STATUS: findings\n", encoding="utf-8"
    )
    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1",
                "summary": "s",
                "severity": "medium",
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
            "domain_tags": ["docs"],
            "risk_level": "low",
            "refactor_depth": "atomic",
            "affected_modules": ["docs"],
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": [],
            "failed_check_signals": [],
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": ["DONE"],
            "triage_prompt_draft": "",
        },
    }
    (findings_dir / "triage.txt").write_text(json.dumps(triage_payload), encoding="utf-8")

    default_route_dir = fake_harness / "fake-clear"
    default_route_dir.mkdir()
    (default_route_dir / "remediation.txt").write_text(
        "Remediation: default route\n", encoding="utf-8"
    )

    _init_git_repo(tmp_path)
    (tmp_path / ".revrem.toml").write_text(
        """
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
model = "fake-clear"
timeout_seconds = 300
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main(
        [
            "--profile",
            "test",
            "--review-model",
            "fake-findings",
            "--artifact-dir",
            "run1",
            "--max-iterations",
            "1",
            "--skip-final-review",
            "--trusted-repo",
        ]
    )

    assert exit_code == 2
    routing = json.loads((tmp_path / "run1" / "routing-1.json").read_text())
    assert "model_proposal" not in routing
    assert routing["policy_decision"]["decision"] == "default_route_applied"
    assert routing["policy_decision"]["matched_rule_ids"] == []
    assert routing["effective_route"]["route_tier"] == "midtier-coder"
    assert routing["effective_route"]["model"] == "fake-clear"
    assert (tmp_path / "run1" / "remediation-1.txt").read_text(encoding="utf-8") == (
        "Remediation: default route\n"
    )


def test_review_classification_security_routes_to_frontier_with_production_loop(
    fake_harness, tmp_path, monkeypatch
):
    findings_dir = fake_harness / "fake-findings"
    findings_dir.mkdir()
    (findings_dir / "review.txt").write_text(
        "Finding: f1\nREVIEW_STATUS: findings\n", encoding="utf-8"
    )
    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1",
                "summary": "Review classifier can hide security findings",
                "severity": "medium",
                "affected_paths": ["src/code_review_loop/core/review_interpretation.py"],
                "rationale": "Classifier changes affect security review routing.",
            }
        ],
        "rejected_findings": [],
        "needs_more_info": [],
        "implementation_order": ["f1"],
        "verification_commands": [],
        "parsing_warnings": [],
        "classification": {
            "domain_tags": ["review-classification", "security"],
            "risk_level": "medium",
            "refactor_depth": "localised",
            "affected_modules": ["code_review_loop.core"],
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": [],
            "failed_check_signals": [],
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": ["Classifier does not hide the finding."],
            "triage_prompt_draft": "Fix the review classifier safety issue.",
        },
    }
    (findings_dir / "triage.txt").write_text(json.dumps(triage_payload), encoding="utf-8")

    frontier_dir = fake_harness / "fake-clear"
    frontier_dir.mkdir()
    (frontier_dir / "remediation.txt").write_text(
        "Remediation: frontier route\n", encoding="utf-8"
    )
    default_dir = fake_harness / "fake-timeout"
    default_dir.mkdir()
    (default_dir / "remediation.txt").write_text("wrong route\n", encoding="utf-8")

    _init_git_repo(tmp_path)
    (tmp_path / ".revrem.toml").write_text(
        """
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
default_route = "codex-midi"

[[profiles.test.triage.routing.rule]]
id = "review-domain-frontier"
when.domain_tags_any = ["security", "review-classification"]
then.route = "codex-frontier"

[profiles.test.triage.routes.codex-midi]
harness = "fake"
model = "fake-timeout"
timeout_seconds = 300

[profiles.test.triage.routes.codex-frontier]
harness = "fake"
model = "fake-clear"
timeout_seconds = 300
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main(
        [
            "--profile",
            "test",
            "--review-model",
            "fake-findings",
            "--artifact-dir",
            "run1",
            "--max-iterations",
            "1",
            "--skip-final-review",
            "--trusted-repo",
        ]
    )

    assert exit_code == 2
    routing = json.loads((tmp_path / "run1" / "routing-1.json").read_text())
    assert routing["policy_decision"]["decision"] == "policy_override"
    assert routing["policy_decision"]["matched_rule_ids"] == ["review-domain-frontier"]
    assert routing["policy_decision"]["rationale"] == (
        "Applied routing rule 'review-domain-frontier' based on triage classification."
    )
    assert routing["effective_route"]["route_tier"] == "codex-frontier"
    assert routing["effective_route"]["model"] == "fake-clear"
    prompt = (tmp_path / "run1" / "remediation-1-prompt.txt").read_text(encoding="utf-8")
    assert "Fix the review classifier safety issue." in prompt
    assert (tmp_path / "run1" / "remediation-1.txt").read_text(encoding="utf-8") == (
        "Remediation: frontier route\n"
    )
