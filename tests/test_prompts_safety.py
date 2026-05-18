from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from code_review_loop import policy, prompts_composer


def test_compose_remediation_prompt_safety_sections_not_truncated(tmp_path):
    # Mandatory header contains role prompt, policy info, and DOD
    triage_payload = {
        "classification": {"risk_level": "high", "refactor_depth": "atomic"},
        "prompt_requirements": {
            "definition_of_done": ["CRITICAL_SAFETY_FIX"]
        }
    }

    resolved_route = policy.ResolvedRoute(
        route_tier="frontier",
        harness="fake",
        model="m1",
        reasoning_effort="high",
        timeout_seconds=60,
        sandbox="s1",
        prompt_fragments=(),
        allow_model_deescalation=False,
        rule_id="sec-rule"
    )

    # Tiny limit that fits header but not the rest
    max_chars = 1000
    original_review = "LONG_REVIEW_" * 200 # 2400 chars

    prompt = prompts_composer.compose_remediation_prompt(
        tmp_path, triage_payload, resolved_route, original_review, max_chars=max_chars
    )

    assert "You are running a bounded review-remediation loop" in prompt
    assert "CRITICAL_SAFETY_FIX" in prompt
    assert "sec-rule" in prompt
    assert len(prompt) <= max_chars
    assert "[... omitted" in prompt # Review context should be truncated


def test_compose_remediation_prompt_fails_if_header_too_large(tmp_path):
    triage_payload = {
        "classification": {"risk_level": "high", "refactor_depth": "atomic"},
        "prompt_requirements": {
            "definition_of_done": ["VERY_LONG_DOD_" * 100]
        }
    }

    resolved_route = policy.ResolvedRoute(
        route_tier="f", harness="h", model="m", reasoning_effort="l", timeout_seconds=1,
        sandbox="s", prompt_fragments=(), allow_model_deescalation=True
    )

    # Header is now > 1000 chars. Use tiny limit.
    with pytest.raises(ValueError, match="mandatory prompt header"):
        prompts_composer.compose_remediation_prompt(
            tmp_path, triage_payload, resolved_route, "rev", max_chars=200
        )
