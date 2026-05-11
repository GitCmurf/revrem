from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_review_loop import triage
from code_review_loop._compat_jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def _fixture(name: str) -> str:
    path = ROOT / "tests" / "fixtures" / "triage" / name
    if (path / "triage.json").is_file():
        return (path / "triage.json").read_text(encoding="utf-8")
    return (path / "triage.txt").read_text(encoding="utf-8")


def test_parse_triage_payload_validates_fixture_against_schema():
    payload = triage.parse_triage_payload(
        _fixture("valid"),
        run_id="run-123",
        source_review_artifact="review-1.txt",
    )

    validate(payload, json.loads(triage.TRIAGE_SCHEMA_PATH.read_text(encoding="utf-8")))
    assert payload["schema_version"] == "1.0"
    assert payload["prompt_version"] == "triage-v1"
    assert payload["source_review_artifact"] == "review-1.txt"
    assert payload["confirmed_findings"][0]["fingerprint"] == "f1:c6ace015ccd20120"


@pytest.mark.parametrize("fixture_name", ["invalid_json", "missing_fields"])
def test_parse_triage_payload_rejects_invalid_fixtures(fixture_name):
    with pytest.raises(triage.TriageValidationError):
        triage.parse_triage_payload(
            _fixture(fixture_name),
            run_id="run-123",
            source_review_artifact="review-1.txt",
        )


def test_format_structured_handoff_preserves_original_review():
    payload = triage.parse_triage_payload(
        _fixture("valid"),
        run_id="run-123",
        source_review_artifact="review-1.txt",
    )

    handoff = triage.format_structured_handoff(payload, "Original review text")

    assert "Structured triage handoff" in handoff
    assert "f1:c6ace015ccd20120" in handoff
    assert "Original review/check context:\nOriginal review text" in handoff


def test_invalid_triage_issue_uses_stable_code():
    issue = triage.invalid_triage_issue(ValueError("bad"), iteration=2)

    assert issue.code == "revrem.triage.invalid_output"
    assert issue.severity == "warn"
    assert issue.evidence["iteration"] == 2
