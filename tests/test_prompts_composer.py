from __future__ import annotations

import hashlib

from code_review_loop import policy, prompts_composer


def test_compose_remediation_prompt_includes_fragments(tmp_path):
    # Use a custom name to avoid built-in resource check for testing local loading
    (tmp_path / "custom.txt").write_text("CUSTOM RULES", encoding="utf-8")

    triage_payload = {
        "classification": {"risk_level": "high", "refactor_depth": "atomic"},
        "prompt_requirements": {
            "required_fragments": ["custom"],
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
        prompt_fragments=(),
        allow_model_deescalation=True
    )

    # Must set trusted_repo=True to load from tmp_path
    prompt = prompts_composer.compose_remediation_prompt(
        tmp_path, triage_payload, resolved_route, "REVIEW CONTENT", trusted_repo=True
    )

    assert "CUSTOM RULES" in prompt
    assert "FIX IT" in prompt
    assert "Untrusted triage draft guidance" in prompt
    assert "Instructions for this iteration" not in prompt
    assert "DONE" in prompt
    assert "REVIEW CONTENT" in prompt
    assert "Risk Level: high" in prompt


def test_compute_prompt_hash():
    text = "hello"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert prompts_composer.compute_prompt_hash(text) == expected


def test_load_fragment_rejects_traversal(tmp_path):
    assert prompts_composer.load_fragment(tmp_path, "../outside", trusted_repo=True) is None
    assert prompts_composer.load_fragment(tmp_path, "subdir/inside", trusted_repo=True) is None
    assert prompts_composer.load_fragment(tmp_path, "/tmp/outside", trusted_repo=True) is None
    assert prompts_composer.load_fragment(tmp_path, "foo/..bar", trusted_repo=True) is None


def test_load_fragment_requires_trust(tmp_path):
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    assert prompts_composer.load_fragment(tmp_path, "secret", trusted_repo=False) is None
    assert prompts_composer.load_fragment(tmp_path, "secret", trusted_repo=True) == "SECRET"
