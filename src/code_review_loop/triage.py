"""Structured triage artifact helpers."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from code_review_loop import artifacts, diagnostics, policy
from code_review_loop._compat_jsonschema import Draft202012Validator

TRIAGE_V1_SCHEMA_VERSION = "1.0"
TRIAGE_V1_PROMPT_VERSION = "triage-v1"
TRIAGE_V1_SCHEMA_RESOURCE = "schemas/triage-v1.schema.json"

TRIAGE_V2_SCHEMA_VERSION = "2.0"
TRIAGE_V2_PROMPT_VERSION = "triage-v2"
TRIAGE_V2_SCHEMA_RESOURCE = "schemas/triage-v2.schema.json"

MAX_SAFETY_SCAN_BYTES = 1024 * 1024


class TriageValidationError(ValueError):
    """Raised when structured triage output does not match the contract."""


def load_prompt(contract: str = "v1") -> str:
    if contract not in {"v1", "v2"}:
        raise ValueError(f"invalid triage contract version: {contract}")
    prompt_name = "triage_v1.txt" if contract == "v1" else "triage_v2.txt"
    return files("code_review_loop.prompts").joinpath(prompt_name).read_text(encoding="utf-8")


def looks_structured_output(output: str) -> bool:
    return output.lstrip().startswith("{")


def parse_triage_payload(
    output: str,
    *,
    run_id: str,
    source_review_artifact: str,
    contract: str = "v1",
) -> dict[str, Any]:
    if contract not in {"v1", "v2"}:
        raise ValueError(f"invalid triage contract version: {contract}")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise TriageValidationError(f"triage output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TriageValidationError("triage output must be a JSON object")

    if contract == "v1":
        schema_version = TRIAGE_V1_SCHEMA_VERSION
        prompt_version = TRIAGE_V1_PROMPT_VERSION
    else:
        schema_version = TRIAGE_V2_SCHEMA_VERSION
        prompt_version = TRIAGE_V2_PROMPT_VERSION

    payload = {
        **payload,
        "schema_version": schema_version,
        "run_id": run_id,
        "prompt_version": payload.get("prompt_version") or prompt_version,
        "source_review_artifact": source_review_artifact,
    }
    validator = Draft202012Validator(_triage_schema(contract))
    errors = list(validator.iter_errors(payload))
    if errors:
        raise TriageValidationError(str(errors[0]))
    return payload


def write_triage_artifact(run_dir: Path, iteration: int, payload: dict[str, Any]) -> Path:
    return artifacts.write_json_artifact(run_dir, f"triage-{iteration}.json", payload)


def write_routing_artifact(run_dir: Path, iteration: int, payload: dict[str, Any]) -> Path:
    return artifacts.write_json_artifact(run_dir, f"routing-{iteration}.json", payload)


def write_routing_outcome_artifact(run_dir: Path, iteration: int, payload: dict[str, Any]) -> Path:
    return artifacts.write_json_artifact(run_dir, f"routing-outcome-{iteration}.json", payload)


def invalid_triage_issue(error: Exception, *, iteration: int) -> diagnostics.DiagnosticIssue:
    return diagnostics.DiagnosticIssue(
        code="revrem.triage.invalid_output",
        severity="warn",
        message=f"Triage output for iteration {iteration} did not match the structured contract.",
        hint="RevRem will continue with the original review context unless triage.on_invalid is stop.",
        evidence={"iteration": iteration, "error": str(error)},
    )


def command_failed_issue(*, iteration: int, returncode: int, artifact: str) -> diagnostics.DiagnosticIssue:
    return diagnostics.DiagnosticIssue(
        code="revrem.triage.command_failed",
        severity="blocking",
        message="Structured triage command failed before producing valid guidance.",
        hint="Inspect the triage output artifact for harness errors or timeouts.",
        evidence={"iteration": iteration, "returncode": returncode, "artifact": artifact},
    )


def validate_routing_payload(payload: dict[str, Any]) -> None:
    schema = json.loads(files("code_review_loop").joinpath("schemas/routing-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise TriageValidationError(str(errors[0]))


def format_structured_handoff(payload: dict[str, Any], original_review: str) -> str:
    parts = ["Structured triage handoff from the previous review:"]

    confirmed = payload.get("confirmed_findings", [])
    if confirmed:
        parts.append("\nConfirmed Actionable Findings:")
        for f in confirmed:
            parts.append(f"- [{f['severity'].upper()}] {f['summary']} (Fingerprint: {f['fingerprint']})")
            parts.append(f"  Rationale: {f['rationale']}")
            if f.get("affected_paths"):
                parts.append(f"  Files: {', '.join(f['affected_paths'])}")

    info = payload.get("needs_more_info", [])
    if info:
        parts.append("\nFindings Requiring More Information:")
        for f in info:
            parts.append(f"- {f['summary']} (Fingerprint: {f['fingerprint']})")
            parts.append(f"  Info Requested: {f['info_requested']}")

    order = payload.get("implementation_order", [])
    if order:
        parts.append("\nSuggested Implementation Order:")
        for i, fp in enumerate(order, 1):
            parts.append(f"{i}. {fp}")

    commands = payload.get("verification_commands", [])
    if commands:
        parts.append("\nSuggested Verification Commands:")
        for cmd in commands:
            parts.append(f"- {cmd}")

    parts.append("\nOriginal review/check context:")
    parts.append(original_review)

    return "\n".join(parts)


def _triage_schema(contract: str = "v1") -> dict[str, Any]:
    resource = TRIAGE_V1_SCHEMA_RESOURCE if contract == "v1" else TRIAGE_V2_SCHEMA_RESOURCE
    schema = json.loads(files("code_review_loop").joinpath(resource).read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise TriageValidationError("triage schema must be a JSON object")
    return schema


def extract_routing_context(
    payload: dict[str, Any],
    cwd: Path,
    failed_checks: tuple[str, ...] = (),
) -> policy.RoutingContext:
    classification = payload.get("classification", {})

    domain_tags = tuple(classification.get("domain_tags", ()))
    risk_level = classification.get("risk_level", "low")
    refactor_depth = classification.get("refactor_depth", "atomic")

    blast_radius = classification.get("estimated_blast_radius", {})
    module_count = blast_radius.get("module_count", 0)

    safety_signals = set(classification.get("safety_signals", ()))

    # Deterministic safety signal detection
    affected_paths = set()
    for finding in payload.get("confirmed_findings", []):
        affected_paths.update(finding.get("affected_paths", []))

    cwd_resolved = cwd.resolve()
    for rel_path in affected_paths:
        try:
            full_path = (cwd / rel_path).resolve()
            if not full_path.is_relative_to(cwd_resolved):
                continue
            if full_path.is_file():
                # Cap file read at 1MB to prevent memory exhaustion.
                # If file is larger, we only scan the first MAX_SAFETY_SCAN_BYTES.
                # This could result in missing signals at the end of huge files, which is a known trade-off.
                with open(full_path, encoding="utf-8", errors="replace") as f:
                    content = f.read(MAX_SAFETY_SCAN_BYTES).lower()
                for signal, tag in SENSITIVE_SIGNALS.items():
                    if signal in content:
                        safety_signals.add(tag)
        except OSError:
            # Ignore files that cannot be read or resolved
            pass

    return policy.RoutingContext(
        domain_tags=domain_tags,
        risk_level=risk_level,
        refactor_depth=refactor_depth,
        module_count=module_count,
        safety_signals=tuple(sorted(safety_signals)),
        failed_checks=failed_checks,
    )


SENSITIVE_SIGNALS = {
    "password": "sensitive-domain:secrets",
    "secret": "sensitive-domain:secrets",
    "api_key": "sensitive-domain:secrets",
    "private_key": "sensitive-domain:secrets",
    "auth": "sensitive-domain:auth",
    "login": "sensitive-domain:auth",
    "token": "sensitive-domain:auth",
    "credit_card": "sensitive-domain:pii",
    "ssn": "sensitive-domain:pii",
    "cryptography": "sensitive-domain:crypto",
    "encrypt": "sensitive-domain:crypto",
    "decrypt": "sensitive-domain:crypto",
}
