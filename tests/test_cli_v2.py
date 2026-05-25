from __future__ import annotations

import json
from argparse import Namespace

import pytest

from code_review_loop.cli.commands import policy as policy_command
from code_review_loop.cli.commands import triage as triage_command
from code_review_loop.cli.commands.triage import triage_explain
from code_review_loop.cli.main import main as cli_main


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
    assert cli_main(["policy", "lint", "--profile", "test"]) == 0


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

    assert cli_main(["policy", "lint", "--profile", "test"]) == 1


def test_policy_review_summarizes_routing_outcomes(tmp_path, capsys):
    routing = {
        "iteration": 1,
        "policy_decision": {
            "decision": "policy_override",
            "rationale": "ok",
            "matched_rule_ids": ["r1"],
        },
        "effective_route": {
            "route_tier": "frontier",
            "harness": "claude",
            "model": "sonnet",
            "reasoning_effort": "high",
            "sandbox": "workspace-write",
            "timeout_seconds": 600,
        },
        "fallbacks_considered": [],
        "prompt": {"path": "p.txt", "sha256": "abc", "bytes": 100, "fragments": []},
    }
    outcome = {
        "exit_code": 0,
        "wall_time_seconds": 10.0,
        "checks_passed": True,
    }
    (tmp_path / "routing-1.json").write_text(json.dumps(routing), encoding="utf-8")
    (tmp_path / "routing-outcome-1.json").write_text(json.dumps(outcome), encoding="utf-8")

    assert cli_main(["policy", "review", "--artifact-dir", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "decision=policy_override" in output
    assert "route=frontier" in output
    assert "harness=claude" in output
    assert "checks_passed=True" in output


def test_policy_main_rejects_unhandled_internal_command(monkeypatch):
    monkeypatch.setattr(
        policy_command,
        "parse_policy_args",
        lambda _argv: Namespace(command="unexpected"),
    )

    with pytest.raises(ValueError, match="unhandled policy command: unexpected"):
        policy_command.main([])


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
    assert triage_explain(tmp_path, 1, output_format="json") == 0


def test_triage_main_rejects_unhandled_internal_command(monkeypatch):
    monkeypatch.setattr(
        triage_command,
        "parse_triage_args",
        lambda _argv: Namespace(command="unexpected"),
    )

    with pytest.raises(ValueError, match="unhandled triage command: unexpected"):
        triage_command.main([])


def test_triage_explain_rejects_non_object_routing_artifact(tmp_path, capsys):
    (tmp_path / "routing-1.json").write_text("[]", encoding="utf-8")

    assert triage_explain(tmp_path, 1) == 1

    assert "routing artifact must be a JSON object" in capsys.readouterr().err


def test_triage_explain_rejects_invalid_json(tmp_path, capsys):
    (tmp_path / "routing-1.json").write_text("{", encoding="utf-8")

    assert triage_explain(tmp_path, 1) == 1

    assert "invalid routing artifact JSON" in capsys.readouterr().err


def test_triage_explain_rejects_non_string_matched_rules(tmp_path, capsys):
    routing = {
        "policy_decision": {"decision": "proposal_accepted", "rationale": "ok", "matched_rule_ids": [1]},
        "effective_route": {
            "route_tier": "t1",
            "harness": "h1",
            "model": "m1",
            "reasoning_effort": "low",
            "sandbox": "s1",
            "timeout_seconds": 60,
        },
        "model_proposal": {"route_tier": "t1", "harness": "h1", "model": "m1", "rationale": "ok"},
        "prompt": {"path": "p.txt", "sha256": "abc", "bytes": 100, "fragments": []},
    }
    (tmp_path / "routing-1.json").write_text(json.dumps(routing), encoding="utf-8")

    assert triage_explain(tmp_path, 1) == 1

    assert "matched_rule_ids must be a string array" in capsys.readouterr().err
