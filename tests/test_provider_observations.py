from __future__ import annotations

from code_review_loop import provider_observations
from code_review_loop.core.ports import CommandResult


def test_codex_observation_parses_banner_and_reports_mismatch():
    result = CommandResult(
        ["codex", "--model", "gpt-5.5", "review"],
        -1,
        stdout=(
            "OpenAI Codex v0.139.0\n"
            "--------\n"
            "model: gpt-5.5\n"
            "provider: openai\n"
            "approval: never\n"
            "sandbox: read-only\n"
            "reasoning effort: xhigh\n"
            "session id: 019eb448-5e00-75c3-a1c8-974cde3731c0\n"
            "--------\n"
            '{"type":"finding","severity":"major"}\n'
        ),
        stderr=(
            "Command timed out after 1200.0 seconds\n"
            'Command: codex --model gpt-5.5 review -c '
            '\'model_reasoning_effort="low"\' --base main\n'
        ),
    )

    observation = provider_observations.codex_observation(
        result,
        phase="review",
        iteration="final",
        requested={
            "model": "gpt-5.5",
            "sandbox": "read-only",
            "reasoning_effort": "low",
        },
    )

    assert observation["banner_detected"] is True
    assert observation["observed"] == {
        "model": "gpt-5.5",
        "provider": "openai",
        "approval": "never",
        "sandbox": "read-only",
        "reasoning_effort": "xhigh",
        "session_id": "019eb448-5e00-75c3-a1c8-974cde3731c0",
    }
    assert observation["raw_provider_finding_count"] == 1
    assert observation["reported_command"].startswith("codex --model gpt-5.5 review")
    assert observation["warnings"] == [
        {
            "kind": "provider_config_mismatch",
            "field": "reasoning_effort",
            "requested": "low",
            "observed": "xhigh",
            "message": "Provider observed reasoning_effort='xhigh' but RevRem requested 'low'.",
        }
    ]


def test_codex_observation_ignores_reviewed_source_without_banner():
    result = CommandResult(
        ["codex", "--model", "gpt-5.5", "review"],
        0,
        stdout=(
            "The patch looks clear.\n"
            "\n"
            "```python\n"
            "model: str | None = None\n"
            "sandbox: str = \"workspace-write\"\n"
            "provider: openai\n"
            "```\n"
            "REVIEW_STATUS: clear\n"
        ),
    )

    observation = provider_observations.codex_observation(
        result,
        phase="review",
        iteration="final",
        requested={
            "model": "gpt-5.5",
            "sandbox": "read-only",
            "reasoning_effort": "low",
        },
    )

    assert observation["banner_detected"] is False
    assert observation["observed"] == {}
    assert observation["warnings"] == []


def test_codex_observation_stops_banner_before_reviewed_source():
    result = CommandResult(
        ["codex", "--model", "gpt-5.5", "review"],
        0,
        stdout=(
            "OpenAI Codex v0.139.0\n"
            "--------\n"
            "model: gpt-5.5\n"
            "provider: openai\n"
            "sandbox: read-only\n"
            "reasoning effort: low\n"
            "--------\n"
            "Reviewed snippet:\n"
            "model: str | None\n"
            "sandbox: str = \"workspace-write\"\n"
            "No findings.\n"
        ),
    )

    observation = provider_observations.codex_observation(
        result,
        phase="review",
        iteration="final",
        requested={
            "model": "gpt-5.5",
            "sandbox": "read-only",
            "reasoning_effort": "low",
        },
    )

    assert observation["banner_detected"] is True
    assert observation["observed"]["model"] == "gpt-5.5"
    assert observation["observed"]["sandbox"] == "read-only"
    assert observation["warnings"] == []


def test_raw_provider_finding_count_requires_standalone_json_line():
    result = CommandResult(
        ["codex", "review"],
        0,
        stdout=(
            'prose mentioning {"type":"finding","severity":"major"} inline\n'
            '{"type":"finding","severity":"major"}\n'
            '  {"type": "status", "status": "reviewing"}\n'
            'not json {"type":"finding"}\n'
        ),
    )

    observation = provider_observations.codex_observation(
        result,
        phase="review",
        iteration="1",
        requested={},
    )

    assert observation["raw_provider_finding_count"] == 1
    assert observation["warnings"] == []
