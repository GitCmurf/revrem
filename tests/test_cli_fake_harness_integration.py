from __future__ import annotations

import json

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import budgets, events, harnesses
from code_review_loop.adapters import subprocess_runner as subprocess_runner_mod
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import RunLoopFailed


def summary_shape(value):
    if isinstance(value, dict):
        return {key: summary_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [summary_shape(value[0])] if value else []
    if value is None:
        return None
    return type(value).__name__


def test_fake_harness_can_drive_clear_review_without_shelling_out(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return subprocess_runner_mod.default_runner(args, cwd, input_text, timeout_seconds)

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="review_clear",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"
    assert summary["harness"] == "fake"
    assert calls == [["revrem-fake-harness", "review", "--scenario", "review_clear"]]
    assert (tmp_path / "artifacts" / "review-1.txt").read_text(encoding="utf-8") == (
        "No actionable findings.\nREVIEW_STATUS: clear\n"
    )


def test_fake_harness_can_drive_remediation_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if list(args) == ["revrem-fake-harness", "review", "--scenario", "review_findings"]:
            object.__setattr__(config, "review_model", "review_clear")
        return subprocess_runner_mod.default_runner(args, cwd, input_text, timeout_seconds)

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        remediation_model="remediation",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"
    assert summary["iterations"][0]["review_status"] == "findings"
    assert "Fake remediation completed." in (
        tmp_path / "artifacts" / "remediation-1.txt"
    ).read_text(encoding="utf-8")


def test_fake_harness_partial_remediation_surfaces_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        remediation_model="remediation_partial",
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, subprocess_runner_mod.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "remediation_failed"
    assert "partial progress" in (tmp_path / "artifacts" / "remediation-1.txt").read_text(
        encoding="utf-8"
    )


def test_fake_harness_can_drive_structured_triage(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if list(args) == ["revrem-fake-harness", "review", "--scenario", "review_findings"]:
            object.__setattr__(config, "review_model", "review_clear")
        return subprocess_runner_mod.default_runner(args, cwd, input_text, timeout_seconds)

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        triage_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        triage_model="triage_valid",
        remediation_model="remediation",
        triage_enabled=True,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))

    assert summary["final_status"] == "clear"
    assert triage_json["confirmed_findings"][0]["fingerprint"] == "f1:fake"


def test_fake_harness_v2_triage_without_routing_uses_direct_remediation(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:fake",
                "summary": "Fix profile merge",
                "severity": "high",
                "affected_paths": ["src/code.py"],
                "rationale": "It is blocking remediation.",
            }
        ],
        "rejected_findings": [],
        "needs_more_info": [],
        "implementation_order": ["f1:fake"],
        "verification_commands": [],
        "parsing_warnings": [],
        "classification": {
            "domain_tags": ["quality"],
            "risk_level": "medium",
            "refactor_depth": "atomic",
            "affected_modules": ["code_review_loop"],
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": [],
            "failed_check_signals": [],
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": ["DONE"],
            "triage_prompt_draft": "Please use the direct remediation fallback.",
        },
    }

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if list(args) == ["revrem-fake-harness", "review", "--scenario", "review_findings"]:
            object.__setattr__(config, "review_model", "review_clear")
        if list(args) == ["revrem-fake-harness", "triage", "--scenario", "triage_valid"]:
            return CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return subprocess_runner_mod.default_runner(args, cwd, input_text, timeout_seconds)

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        triage_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        triage_model="triage_valid",
        remediation_model="remediation",
        triage_enabled=True,
        triage_contract="v2",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
    run_dir = tmp_path / "artifacts"

    assert summary["final_status"] == "clear"
    triage_json = json.loads((run_dir / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["schema_version"] == "2.0"
    assert triage_json["prompt_version"] == "triage-v2"
    assert (run_dir / "remediation-1.txt").read_text(
        encoding="utf-8"
    ) == "Fake remediation completed.\n"


def test_fake_and_codex_summary_shapes_are_structurally_equivalent(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    fake_dir = tmp_path / "fake"
    codex_dir = tmp_path / "codex"
    fake_dir.mkdir()
    codex_dir.mkdir()

    fake_config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=fake_dir,
        artifact_dir=fake_dir / "artifacts",
        review_harness="fake",
        review_model="review_clear",
    )
    codex_config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=codex_dir,
        artifact_dir=codex_dir / "artifacts",
        review_model="review_clear",
    )

    def codex_runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(
            list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n"
        )

    fake_summary = runner_mod.run_loop(fake_config, subprocess_runner_mod.default_runner).to_dict()
    codex_summary = runner_mod.run_loop(codex_config, codex_runner).to_dict()

    assert summary_shape(fake_summary) == summary_shape(codex_summary)
    assert fake_summary["harness"] == "fake"
    assert codex_summary["harness"] == "codex"
    assert fake_summary["final_status"] == codex_summary["final_status"] == "clear"


def test_fake_harness_timeout_surfaces_as_review_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="timeout",
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, subprocess_runner_mod.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "review_failed"
    assert "Fake harness timeout" in (tmp_path / "artifacts" / "review-1.txt").read_text(
        encoding="utf-8"
    )


def test_fake_harness_cancellation_uses_controlled_cancellation_path(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="cancellation",
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, subprocess_runner_mod.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "cancelled"
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    assert truncated is False
    assert any(event.kind == "cancellation" for event in records)


def test_fake_harness_unsupported_surfaces_as_review_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="unsupported",
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, subprocess_runner_mod.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "review_failed"
    assert "unsupported" in (tmp_path / "artifacts" / "review-1.txt").read_text(encoding="utf-8")


def test_fake_harness_token_charge_drives_budget_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="cost_ceiling",
        budget_config=budgets.BudgetConfig(max_tokens=10),
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, subprocess_runner_mod.default_runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"
    assert summary["budgets"]["tokens"] == 10
    assert summary["budgets"]["usd"] is None
    assert truncated is False
    assert any(event.kind == "cost_charge" and event.payload["tokens"] == 10 for event in records)
    assert any(
        event.kind == "cost_ceiling_hit" and event.payload["ceiling"] == "tokens"
        for event in records
    )
