from __future__ import annotations

import json

from code_review_loop import triage


def test_extract_routing_context_with_safety_signals(tmp_path):
    # Create a file with sensitive keywords
    auth_py = tmp_path / "auth.py"
    auth_py.write_text("def login(): password = '123'", encoding="utf-8")

    payload = {
        "confirmed_findings": [
            {
                "affected_paths": ["auth.py"],
                "fingerprint": "f1",
                "summary": "s",
                "severity": "h",
                "rationale": "r",
            }
        ],
        "classification": {
            "domain_tags": ["api"],
            "risk_level": "medium",
            "refactor_depth": "atomic",
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": ["low-confidence-signal"],
        },
    }

    context = triage.extract_routing_context(payload, tmp_path)

    assert "api" in context.domain_tags
    assert context.risk_level == "medium"
    assert "low-confidence-signal" in context.safety_signals
    assert "sensitive-domain:auth" in context.safety_signals
    assert context.module_count == 1


def test_extract_routing_context_folds_deterministic_domain_into_tags(tmp_path):
    # When the model omits a sensitive domain tag but a confirmed finding's file
    # contains sensitive content, the deterministic detection must surface both
    # as a safety signal (provenance) and as a plain domain tag so that natural
    # domain_tags_any rules still escalate.
    auth_py = tmp_path / "auth.py"
    auth_py.write_text("def login(): ...", encoding="utf-8")

    payload = {
        "confirmed_findings": [
            {
                "affected_paths": ["auth.py"],
                "fingerprint": "f1",
                "summary": "s",
                "severity": "h",
                "rationale": "r",
            }
        ],
        "classification": {
            "domain_tags": ["docs"],
            "risk_level": "low",
            "refactor_depth": "atomic",
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
        },
    }

    context = triage.extract_routing_context(payload, tmp_path)

    assert "auth" in context.domain_tags
    assert "sensitive-domain:auth" in context.safety_signals


def test_load_schema_uses_cache(monkeypatch):
    triage._load_schema.cache_clear()
    calls = {"read_text": 0}

    class FakeResource:
        def read_text(self, encoding: str) -> str:
            assert encoding == "utf-8"
            calls["read_text"] += 1
            return json.dumps({"type": "object"})

    class FakePackage:
        def joinpath(self, resource: str) -> FakeResource:
            assert resource == "schemas/triage-v1.schema.json"
            return FakeResource()

    monkeypatch.setattr(triage, "files", lambda package: FakePackage())

    first = triage._load_schema("schemas/triage-v1.schema.json")
    second = triage._load_schema("schemas/triage-v1.schema.json")

    assert first == {"type": "object"}
    assert second == {"type": "object"}
    assert calls["read_text"] == 1

    triage._load_schema.cache_clear()
