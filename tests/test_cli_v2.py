from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_review_loop import cli


def test_policy_lint_success(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    toml = """
[profiles.test.triage]
contract = "v2"
routing.enabled = true
routing.default_route = "m"
[profiles.test.triage.routes.m]
harness = "codex"
"""
    path = tmp_path / ".revrem.toml"
    path.write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Run cli.main with policy lint
    assert cli.main(["policy", "lint", "--profile", "test"]) == 0


def test_policy_lint_failure(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    # Unknown route
    toml = """
[profiles.test.triage]
contract = "v2"
routing.enabled = true
routing.default_route = "missing"
"""
    path = tmp_path / ".revrem.toml"
    path.write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["policy", "lint", "--profile", "test"]) == 1


def test_triage_explain_json(tmp_path):
    routing = {
        "policy_decision": {"decision": "proposal_accepted", "rationale": "ok", "matched_rule_ids": []},
        "effective_route": {"route_tier": "t1", "harness": "h1", "model": "m1", "reasoning_effort": "low", "sandbox": "s1", "timeout_seconds": 60},
        "model_proposal": {"route_tier": "t1", "harness": "h1", "model": "m1", "rationale": "ok"},
        "prompt": {"path": "p.txt", "sha256": "abc", "bytes": 100, "fragments": []}
    }
    (tmp_path / "routing-1.json").write_text(json.dumps(routing), encoding="utf-8")

    # We can't easily capture stdout from cli.main if it uses print()
    # But we can test the underlying function
    assert cli.triage_explain(tmp_path, 1, output_format="json") == 0
