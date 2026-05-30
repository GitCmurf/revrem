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


def test_parse_triage_payload_v2_validates_fixture_against_schema():
    payload = triage.parse_triage_payload(
        _fixture("valid_v2"),
        run_id="run-123",
        source_review_artifact="review-1.txt",
        contract="v2",
    )

    validate(
        payload,
        json.loads(files("code_review_loop").joinpath("schemas/triage-v2.schema.json").read_text(encoding="utf-8")),
    )
    assert payload["schema_version"] == "2.0"
    assert payload["prompt_version"] == "triage-v2"
    assert payload["classification"]["risk_level"] == "medium"
    assert payload["route_proposal"]["route_tier"] == "midtier"
    assert payload["prompt_requirements"]["required_fragments"] == ["engineering-principles"]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "sensitive_finding",
        "architectural_refactor",
        "careful_refactor",
        "trivial_atomic",
        "invalid_route",
        "unavailable_harness",
    ],
)
def test_parse_triage_payload_v2_validates_policy_scenario_fixtures(fixture_name):
    payload = triage.parse_triage_payload(
        _fixture(fixture_name),
        run_id="run-123",
        source_review_artifact="review-1.txt",
        contract="v2",
    )

    validate(
        payload,
        json.loads(files("code_review_loop").joinpath("schemas/triage-v2.schema.json").read_text(encoding="utf-8")),
    )
    assert payload["confirmed_findings"]
    assert payload["classification"]["estimated_blast_radius"]["finding_count"] == 1


def test_parse_triage_payload_v2_accepts_minimal_reasoning_effort():
    fixture = json.loads(_fixture("valid_v2"))
    fixture["route_proposal"]["reasoning_effort"] = "minimal"

    payload = triage.parse_triage_payload(
        json.dumps(fixture),
        run_id="run-123",
        source_review_artifact="review-1.txt",
        contract="v2",
    )

    assert payload["route_proposal"]["reasoning_effort"] == "minimal"


def test_parse_triage_payload_v2_normalizes_review_priority_severities():
    fixture = json.loads(_fixture("valid_v2"))
    fixture["confirmed_findings"][0]["severity"] = "P2"
    fixture["rejected_findings"] = [
        {
            "fingerprint": "f1:rejected",
            "summary": "False positive",
            "severity": "p3",
            "affected_paths": ["src/code_review_loop/triage.py"],
            "rationale": "The reported failure is not present.",
            "rejection_reason": "Existing guard handles this path.",
        }
    ]

    payload = triage.parse_triage_payload(
        json.dumps(fixture),
        run_id="run-123",
        source_review_artifact="review-1.txt",
        contract="v2",
    )

    assert payload["confirmed_findings"][0]["severity"] == "medium"
    assert payload["rejected_findings"][0]["severity"] == "low"
    assert len(payload["parsing_warnings"]) >= 2


def test_parse_triage_payload_v2_fails_on_v1_contract():
    # v1 fixture doesn't have classification/routing, so it should fail v2 schema
    with pytest.raises(triage.TriageValidationError):
        triage.parse_triage_payload(
            _fixture("valid"),
            run_id="run-123",
            source_review_artifact="review-1.txt",
            contract="v2",
        )


def test_load_prompt_v2_includes_v2_fields():
    prompt = triage.load_prompt(contract="v2")

    assert "classification" in prompt
    assert "route_proposal" in prompt
    assert "prompt_requirements" in prompt
    assert "triage-v2" in prompt


def test_write_triage_artifact_preserves_payload_schema_version(tmp_path):
    payload = {
        "schema_version": "2.0",
        "run_id": "run-123",
        "source_review_artifact": "review-1.txt",
        "prompt_version": "triage-v2",
    }

    path = triage.write_triage_artifact(tmp_path, 1, payload)

    assert path.name == "triage-1.json"
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_write_routing_artifacts(tmp_path):
    payload = {"effective_route": {"harness": "codex", "model": "m1"}}
    path = triage.write_routing_artifact(tmp_path, 1, payload)
    assert path.name == "routing-1.json"
    assert json.loads(path.read_text()) == {**payload, "schema_version": "1.0"}


def test_write_routing_outcome_artifacts(tmp_path):
    payload = {"exit_code": 0, "wall_time_seconds": 10.5}
    path = triage.write_routing_outcome_artifact(tmp_path, 1, payload)
    assert path.name == "routing-outcome-1.json"
    assert json.loads(path.read_text()) == {**payload, "schema_version": "1.0"}
