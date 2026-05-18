from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from code_review_loop import policy, prompts_composer


def test_compose_remediation_prompt_includes_fragments(tmp_path):
    (tmp_path / "engineering-principles-v1.1.md").write_text("CORE PRINCIPLES", encoding="utf-8")
    (tmp_path / "custom.txt").write_text("CUSTOM RULES", encoding="utf-8")
    
    triage_payload = {
        "classification": {"risk_level": "high", "refactor_depth": "atomic"},
        "prompt_requirements": {
            "required_fragments": ["engineering-principles"],
            "triage_prompt_draft": "FIX IT",
            "definition_of_done": ["DONE"]
        }
    }
    
    resolved_route = policy.ResolvedRoute(
        route_tier="t1",
        harness="h1",
        model="m1",
        reasoning_effort="low",
        timeout_seconds=60,
        sandbox="s1",
        prompt_fragments=("custom",),
        allow_model_deescalation=True
    )
    
    prompt = prompts_composer.compose_remediation_prompt(
        tmp_path, triage_payload, resolved_route, "REVIEW CONTENT"
    )
    
    assert "CORE PRINCIPLES" in prompt
    assert "CUSTOM RULES" in prompt
    assert "FIX IT" in prompt
    assert "DONE" in prompt
    assert "REVIEW CONTENT" in prompt
    assert "Risk Level: high" in prompt


def test_compute_prompt_hash():
    text = "hello"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert prompts_composer.compute_prompt_hash(text) == expected
