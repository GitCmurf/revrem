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
            'Extra tool output {"type":"finding","severity":"major"}\n'
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
