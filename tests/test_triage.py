from __future__ import annotations

import json
from importlib.resources import files
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

    validate(
        payload,
        json.loads(files("code_review_loop").joinpath(triage.TRIAGE_SCHEMA_RESOURCE).read_text(encoding="utf-8")),
    )
    assert payload["schema_version"] == "1.0"
    assert payload["prompt_version"] == "triage-v1"
    assert payload["source_review_artifact"] == "review-1.txt"
    assert payload["confirmed_findings"][0]["fingerprint"] == "f1:c6ace015ccd20120"


def test_rejected_only_triage_fixture_preserves_false_positive_rationale():
    payload = triage.parse_triage_payload(
        _fixture("rejected_only"),
        run_id="run-123",
        source_review_artifact="review-1.txt",
    )

    assert payload["confirmed_findings"] == []
    assert payload["rejected_findings"][0]["fingerprint"] == "f1:rejected001"
    assert payload["rejected_findings"][0]["rejection_reason"]


def test_labelled_triage_fixture_precision_meets_plan_target():
    payload = triage.parse_triage_payload(
        _fixture("valid"),
        run_id="run-123",
        source_review_artifact="review-1.txt",
    )
    labelled_true_positive_fingerprints = {"f1:c6ace015ccd20120"}
    confirmed = {item["fingerprint"] for item in payload["confirmed_findings"]}
    precision = len(confirmed & labelled_true_positive_fingerprints) / len(confirmed)

    assert precision >= 0.85


def test_packaged_triage_schema_matches_reference_copy():
    packaged_schema = json.loads(
        files("code_review_loop").joinpath("schemas/triage-v1.schema.json").read_text(encoding="utf-8")
    )
    reference_schema = json.loads(
        (ROOT / "docs" / "52-api" / "schemas" / "triage-v1.schema.json").read_text(encoding="utf-8")
    )

    assert packaged_schema == reference_schema


def test_default_triage_prompt_spells_out_the_structured_contract():
    prompt = triage.load_prompt()

    for fragment in (
        "confirmed_findings",
        "rejected_findings",
        "needs_more_info",
        "implementation_order",
        "verification_commands",
        "parsing_warnings",
        "fingerprint",
        "affected_paths",
        "rejection_reason",
        "info_requested",
        "Do not invent a new fingerprint",
    ):
        assert fragment in prompt


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
