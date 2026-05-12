"""Structured triage artifact helpers."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from code_review_loop import artifacts, diagnostics
from code_review_loop._compat_jsonschema import Draft202012Validator

TRIAGE_SCHEMA_VERSION = "1.0"
TRIAGE_PROMPT_VERSION = "triage-v1"
TRIAGE_SCHEMA_RESOURCE = "schemas/triage-v1.schema.json"


class TriageValidationError(ValueError):
    """Raised when structured triage output does not match the v1 contract."""


def load_prompt() -> str:
    return files("code_review_loop.prompts").joinpath("triage_v1.txt").read_text(encoding="utf-8")


def looks_structured_output(output: str) -> bool:
    return output.lstrip().startswith("{")


def parse_triage_payload(
    output: str,
    *,
    run_id: str,
    source_review_artifact: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise TriageValidationError(f"triage output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TriageValidationError("triage output must be a JSON object")
    payload = {
        **payload,
        "schema_version": TRIAGE_SCHEMA_VERSION,
        "run_id": run_id,
        "prompt_version": payload.get("prompt_version") or TRIAGE_PROMPT_VERSION,
        "source_review_artifact": source_review_artifact,
    }
    validator = Draft202012Validator(_triage_schema())
    errors = list(validator.iter_errors(payload))
    if errors:
        raise TriageValidationError(str(errors[0]))
    return payload


def write_triage_artifact(run_dir: Path, iteration: int, payload: dict[str, Any]) -> Path:
    return artifacts.write_json_artifact(run_dir, f"triage-{iteration}.json", payload)


def invalid_triage_issue(error: Exception, *, iteration: int) -> diagnostics.DiagnosticIssue:
    return diagnostics.DiagnosticIssue(
        code="revrem.triage.invalid_output",
        severity="warn",
        message=f"Triage output for iteration {iteration} did not match the structured contract.",
        hint="RevRem will continue with the original review context unless triage.on_invalid is stop.",
        evidence={"iteration": iteration, "error": str(error)},
    )


def format_structured_handoff(payload: dict[str, Any], original_review: str) -> str:
    return (
        "Structured triage handoff from the previous review:\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n\n"
        "Original review/check context:\n"
        f"{original_review}"
    )


def diagnostics_payload(issue: diagnostics.DiagnosticIssue) -> dict[str, Any]:
    return diagnostics.doctor_payload([issue])


def _triage_schema() -> dict[str, Any]:
    schema = json.loads(files("code_review_loop").joinpath(TRIAGE_SCHEMA_RESOURCE).read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise TriageValidationError("triage schema must be a JSON object")
    return schema
