from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_review_loop import harnesses
from code_review_loop._compat_jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def test_codex_adapter_builds_review_command():
    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="codex",
            role="review",
            executable="codex",
            base="main",
            model="gpt-5.5",
            reasoning_effort="medium",
        )
    )

    assert command == [
        "codex",
        "-c",
        'model_reasoning_effort="medium"',
        "--model",
        "gpt-5.5",
        "review",
        "--base",
        "main",
    ]


def test_codex_adapter_builds_remediation_exec_command():
    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="codex",
            role="remediation",
            executable="codex",
            model="gpt-5.4-mini",
            reasoning_effort="low",
            sandbox="workspace-write",
            color="never",
            json_output=True,
            output_last_message_path=Path("last.txt"),
        )
    )

    assert command[:6] == [
        "codex",
        "exec",
        "-c",
        'model_reasoning_effort="low"',
        "--full-auto",
        "--sandbox",
    ]
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[command.index("--color") + 1] == "never"
    assert "--json" in command
    assert command[command.index("--model") + 1] == "gpt-5.4-mini"
    assert command[-3:] == ["--output-last-message", "last.txt", "-"]


def test_reserved_harnesses_are_valid_but_not_executable():
    with pytest.raises(NotImplementedError, match="claude"):
        harnesses.build_phase_command(
            harnesses.PhaseCommandRequest(
                harness="claude",
                role="review",
                executable="claude",
            )
        )


def test_codex_capabilities_validate_against_schema():
    schema = json.loads(
        (ROOT / "docs/52-api/schemas/harness-capabilities-v1.schema.json").read_text(encoding="utf-8")
    )
    payload = harnesses.harness_capabilities_payload("codex")

    validate(payload, schema)

    assert payload["schema_version"] == "1.0"
    assert payload["review_supported"] is True
    assert payload["remediation_supported"] is True
    assert payload["triage_supported"] is True
    assert payload["commit_message_supported"] is True
    assert payload["cost_reporting"] == "none"


def test_fake_harness_is_hidden_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv(harnesses.FAKE_HARNESS_ENV, raising=False)

    with pytest.raises(ValueError, match="review.harness"):
        harnesses.validate_harness_name("fake", field="review.harness")

    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    harnesses.validate_harness_name("fake", field="review.harness")
    payload = harnesses.harness_capabilities_payload("fake")
    assert payload["structured_output_supported"] is True
    assert payload["cost_reporting"] == "tokens"


def test_fake_harness_builds_internal_command_when_enabled(monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="fake",
            role="review",
            executable="fake",
            model="review_clear",
        )
    )

    assert command == ["revrem-fake-harness", "review", "--scenario", "review_clear"]


def test_fake_harness_command_replays_fixture(monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    returncode, stdout, stderr = harnesses.run_fake_harness_command(
        ["revrem-fake-harness", "review", "--scenario", "review_clear"]
    )

    assert returncode == 0
    assert "REVIEW_STATUS: clear" in stdout
    assert stderr == ""


def test_fake_harness_command_is_env_gated(monkeypatch):
    monkeypatch.delenv(harnesses.FAKE_HARNESS_ENV, raising=False)

    returncode, stdout, stderr = harnesses.run_fake_harness_command(
        ["revrem-fake-harness", "review", "--scenario", "review_clear"]
    )

    assert returncode == 2
    assert stdout == ""
    assert harnesses.FAKE_HARNESS_ENV in stderr


def test_fake_harness_command_can_simulate_timeout(monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    returncode, stdout, stderr = harnesses.run_fake_harness_command(
        ["revrem-fake-harness", "review", "--scenario", "timeout"]
    )

    assert returncode == -1
    assert stdout == ""
    assert "timeout" in stderr


def test_fake_harness_command_can_simulate_cancellation(monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    with pytest.raises(KeyboardInterrupt):
        harnesses.run_fake_harness_command(
            ["revrem-fake-harness", "review", "--scenario", "cancellation"]
        )


def test_fake_harness_command_can_simulate_unsupported(monkeypatch):
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")

    returncode, stdout, stderr = harnesses.run_fake_harness_command(
        ["revrem-fake-harness", "review", "--scenario", "unsupported"]
    )

    assert returncode == 2
    assert stdout == ""
    assert "unsupported" in stderr
