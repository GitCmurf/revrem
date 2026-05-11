from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from jsonschema.validators import Draft202012Validator

from code_review_loop import diagnostics

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "52-api" / "schemas"


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_schema_files_are_valid_draft_2020_12():
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_doctor_payload_validates_against_diagnostics_schema():
    issues = [
        diagnostics.DiagnosticIssue(
            code="revrem.preflight.invalid_base",
            severity="blocking",
            message="Base ref 'missing' does not resolve.",
            hint="Fetch the target branch or pass --base with an existing ref.",
            evidence={"base": "missing"},
        )
    ]

    jsonschema.validate(
        diagnostics.doctor_payload(issues),
        _load_schema("diagnostics-v1.schema.json"),
    )


def test_skeleton_schema_requires_schema_version():
    schema = _load_schema("summary-v1.schema.json")

    jsonschema.validate({"schema_version": "1.0", "extra": "allowed"}, schema)
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors({"extra": "missing version"}))
