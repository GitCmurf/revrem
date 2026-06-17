"""Structured triage artifact helpers."""

from __future__ import annotations

import functools
import json
from importlib.resources import files
from pathlib import Path
from typing import Any, TypeAlias

from code_review_loop import artifacts, diagnostics, policy
from code_review_loop._compat_jsonschema import Draft202012Validator

TRIAGE_V1_SCHEMA_VERSION = "1.0"
TRIAGE_V1_PROMPT_VERSION = "triage-v1"
TRIAGE_V1_SCHEMA_RESOURCE = "schemas/triage-v1.schema.json"

TRIAGE_V2_SCHEMA_VERSION = "2.0"
TRIAGE_V2_PROMPT_VERSION = "triage-v2"
TRIAGE_V2_SCHEMA_RESOURCE = "schemas/triage-v2.schema.json"
ROUTING_V1_SCHEMA_RESOURCE = "schemas/routing-v1.schema.json"

MAX_SAFETY_SCAN_BYTES = 1024 * 1024
_REVIEW_PRIORITY_SEVERITIES = {
    "P0": "critical",
    "P1": "high",
    "P2": "medium",
    "P3": "low",
    "P4": "info",
}

RoutingContextCache: TypeAlias = dict[
    tuple[Path, int, int], tuple[tuple[str, ...], tuple[str, ...]]
]


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
    payload = _normalize_review_priority_severities(payload)
    if contract == "v2":
        payload = _normalize_v2_route_proposal(payload)
        payload = _normalize_v2_definition_of_done_placement(payload)
    validator = Draft202012Validator(_triage_schema(contract))
    errors = list(validator.iter_errors(payload))
    if errors:
        raise TriageValidationError(str(errors[0]))
    return payload


def _normalize_review_priority_severities(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_warnings = normalized.get("parsing_warnings")
    warnings_can_update = raw_warnings is None or isinstance(raw_warnings, list)
    warnings, changed = _normalize_parsing_warnings(raw_warnings or [])
    for collection_name in ("confirmed_findings", "rejected_findings", "needs_more_info"):
        collection = normalized.get(collection_name)
        if not isinstance(collection, list):
            continue
        normalized_collection: list[Any] = []
        for item in collection:
            if not isinstance(item, dict):
                normalized_collection.append(item)
                continue
            normalized_item = dict(item)
            raw_severity = normalized_item.get("severity")
            if isinstance(raw_severity, str):
                mapped = _REVIEW_PRIORITY_SEVERITIES.get(raw_severity.strip().upper())
                if mapped is not None:
                    normalized_item["severity"] = mapped
                    if warnings_can_update:
                        warnings.append(
                            f"Normalized {collection_name} severity {raw_severity!r} to {mapped!r}."
                        )
                    changed = True
            raw_info_requested = normalized_item.get("info_requested")
            raw_fingerprint = normalized_item.get("fingerprint")
            if collection_name == "needs_more_info" and raw_fingerprint is None:
                normalized_item["fingerprint"] = f"review-comment:{len(normalized_collection) + 1}"
                if warnings_can_update:
                    warnings.append(
                        "Normalized needs_more_info missing fingerprint to "
                        f"{normalized_item['fingerprint']} fallback."
                    )
                changed = True
            if (
                collection_name == "needs_more_info"
                and isinstance(raw_info_requested, list)
                and all(isinstance(part, str) for part in raw_info_requested)
            ):
                normalized_item["info_requested"] = "\n".join(raw_info_requested)
                if warnings_can_update:
                    warnings.append(
                        "Normalized needs_more_info info_requested list to a newline-delimited string."
                    )
                changed = True
            normalized_collection.append(normalized_item)
        normalized[collection_name] = normalized_collection
    if changed and warnings_can_update:
        normalized["parsing_warnings"] = warnings
    return normalized


def _normalize_parsing_warnings(raw_warnings: Any) -> tuple[list[Any], bool]:
    if not isinstance(raw_warnings, list):
        return [], False
    normalized: list[Any] = []
    changed = False
    for warning in raw_warnings:
        if isinstance(warning, str):
            normalized.append(warning)
            continue
        if isinstance(warning, dict) and isinstance(warning.get("message"), str):
            normalized.append(warning["message"])
            changed = True
            continue
        normalized.append(warning)
    return normalized, changed


def _normalize_v2_definition_of_done_placement(payload: dict[str, Any]) -> dict[str, Any]:
    """Move a common model mistake into the schema-sanctioned location."""

    prompt_requirements = payload.get("prompt_requirements")
    if not isinstance(prompt_requirements, dict):
        return payload

    normalized = dict(payload)
    normalized_prompt_requirements = dict(prompt_requirements)
    raw_dod = normalized_prompt_requirements.get("definition_of_done")
    raw_warnings = normalized.get("parsing_warnings")
    warnings_can_update = raw_warnings is None or isinstance(raw_warnings, list)
    warnings, _ = _normalize_parsing_warnings(raw_warnings or [])
    merged_dod = list(raw_dod) if isinstance(raw_dod, list) else []
    changed = False

    for collection_name in ("confirmed_findings", "needs_more_info", "rejected_findings"):
        collection = normalized.get(collection_name)
        if not isinstance(collection, list):
            continue
        normalized_collection: list[Any] = []
        for item in collection:
            if not isinstance(item, dict):
                normalized_collection.append(item)
                continue
            misplaced = item.get("definition_of_done")
            if misplaced is None:
                normalized_collection.append(item)
                continue
            if not (
                isinstance(misplaced, list)
                and all(isinstance(part, str) for part in misplaced)
            ):
                normalized_collection.append(item)
                continue
            normalized_item = dict(item)
            normalized_item.pop("definition_of_done")
            merged_dod.extend(misplaced)
            changed = True
            if warnings_can_update:
                fingerprint = normalized_item.get("fingerprint")
                suffix = f" for {fingerprint}" if isinstance(fingerprint, str) else ""
                warnings.append(
                    "Moved misplaced finding definition_of_done entries into "
                    f"prompt_requirements.definition_of_done{suffix}."
                )
            normalized_collection.append(normalized_item)
        normalized[collection_name] = normalized_collection

    if not changed:
        return payload
    normalized_prompt_requirements["definition_of_done"] = merged_dod
    normalized["prompt_requirements"] = normalized_prompt_requirements
    if warnings_can_update:
        normalized["parsing_warnings"] = warnings
    return normalized


def _normalize_v2_route_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common route proposal timeout encodings before schema validation."""

    route_proposal = payload.get("route_proposal")
    if not isinstance(route_proposal, dict):
        return payload
    if "timeout_seconds" not in route_proposal:
        return payload

    raw_timeout = route_proposal.get("timeout_seconds")
    if raw_timeout is not None and not (
        isinstance(raw_timeout, str) and raw_timeout.strip().lower() == "none"
    ):
        return payload

    normalized = dict(payload)
    normalized_route_proposal = dict(route_proposal)
    normalized_route_proposal["timeout_seconds"] = 0
    normalized["route_proposal"] = normalized_route_proposal

    raw_warnings = normalized.get("parsing_warnings")
    warnings_can_update = raw_warnings is None or isinstance(raw_warnings, list)
    if warnings_can_update:
        warnings, _ = _normalize_parsing_warnings(raw_warnings or [])
        warnings.append(
            "Normalized route_proposal.timeout_seconds to 0 for an unbounded route timeout."
        )
        normalized["parsing_warnings"] = warnings
    return normalized


def write_triage_artifact(run_dir: Path, iteration: int, payload: dict[str, Any]) -> Path:
    return artifacts.write_json_artifact(
        run_dir,
        f"triage-{iteration}.json",
        payload,
        schema_version=str(payload.get("schema_version", artifacts.JSON_SCHEMA_VERSION)),
    )


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


def command_failed_issue(
    *, iteration: int, returncode: int, artifact: str
) -> diagnostics.DiagnosticIssue:
    return diagnostics.DiagnosticIssue(
        code="revrem.triage.command_failed",
        severity="blocking",
        message="Structured triage command failed before producing valid guidance.",
        hint="Inspect the triage output artifact for harness errors or timeouts.",
        evidence={"iteration": iteration, "returncode": returncode, "artifact": artifact},
    )


def validate_routing_payload(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(_load_schema(ROUTING_V1_SCHEMA_RESOURCE))
    errors = list(validator.iter_errors(payload))
    if errors:
        raise TriageValidationError(str(errors[0]))


def format_structured_handoff(payload: dict[str, Any], original_review: str) -> str:
    parts = ["Structured triage handoff from the previous review:"]

    confirmed = payload.get("confirmed_findings", [])
    if confirmed:
        parts.append("\nConfirmed Actionable Findings:")
        for f in confirmed:
            parts.append(
                f"- [{f['severity'].upper()}] {f['summary']} (Fingerprint: {f['fingerprint']})"
            )
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

    prompt_requirements = payload.get("prompt_requirements", {})
    if isinstance(prompt_requirements, dict):
        fragments = prompt_requirements.get("required_fragments", [])
        if fragments:
            parts.append("\nRequested Prompt Fragments:")
            for fragment in fragments:
                parts.append(f"- {fragment}")
        dod = prompt_requirements.get("definition_of_done", [])
        if dod:
            parts.append("\nDefinition of Done:")
            for item in dod:
                parts.append(f"- {item}")
        draft = prompt_requirements.get("triage_prompt_draft")
        if isinstance(draft, str) and draft.strip():
            parts.append("\nTriage Draft Instructions:")
            parts.append(draft.strip())

    classification = payload.get("classification", {})
    if isinstance(classification, dict):
        risk = classification.get("risk_level")
        depth = classification.get("refactor_depth")
        if risk or depth:
            parts.append("\nTriage Classification:")
            if risk:
                parts.append(f"- Risk level: {risk}")
            if depth:
                parts.append(f"- Refactor depth: {depth}")

    parts.append("\nOriginal review/check context:")
    parts.append(original_review)

    return "\n".join(parts)


# Cache imported schema resources so repeated triage validation does not reread package data.
@functools.cache
def _load_schema(resource: str) -> dict[str, Any]:
    schema = json.loads(files("code_review_loop").joinpath(resource).read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise TriageValidationError("schema must be a JSON object")
    return schema


def _triage_schema(contract: str = "v1") -> dict[str, Any]:
    if contract == "v1":
        resource = TRIAGE_V1_SCHEMA_RESOURCE
    elif contract == "v2":
        resource = TRIAGE_V2_SCHEMA_RESOURCE
    else:
        raise ValueError(f"invalid triage contract: {contract}")
    return _load_schema(resource)


def extract_routing_context(
    payload: dict[str, Any],
    cwd: Path,
    failed_checks: tuple[str, ...] = (),
    *,
    cache: RoutingContextCache | None = None,
) -> policy.RoutingContext:
    classification = payload.get("classification", {})

    domain_tags = set(classification.get("domain_tags", ()))
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
    for rel_path in sorted(affected_paths):
        try:
            full_path = (cwd / rel_path).resolve()
            if not full_path.is_relative_to(cwd_resolved):
                continue
            if not full_path.is_file():
                continue
            stat = full_path.stat()
            cache_key = (full_path, stat.st_mtime_ns, stat.st_size)
            cached = cache.get(cache_key) if cache is not None else None
            if cached is None:
                detected_signals, detected_domains = _scan_sensitive_signals(full_path)
                if cache is not None:
                    cache[cache_key] = (detected_signals, detected_domains)
            else:
                detected_signals, detected_domains = cached
            safety_signals.update(detected_signals)
            domain_tags.update(detected_domains)
        except OSError:
            # Ignore files that cannot be read or resolved
            pass

    return policy.RoutingContext(
        domain_tags=tuple(sorted(domain_tags)),
        risk_level=risk_level,
        refactor_depth=refactor_depth,
        module_count=module_count,
        safety_signals=tuple(sorted(safety_signals)),
        failed_checks=failed_checks,
    )


def _scan_sensitive_signals(full_path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    # Cap file read at 1MB to prevent memory exhaustion. If file is larger, we
    # only scan the first MAX_SAFETY_SCAN_BYTES; signals beyond the cap are a
    # deliberate safety/performance trade-off.
    with open(full_path, encoding="utf-8", errors="replace") as f:
        content = f.read(MAX_SAFETY_SCAN_BYTES).lower()
    safety_signals = set()
    domain_tags = set()
    for signal, tag in SENSITIVE_SIGNALS.items():
        if signal in content:
            safety_signals.add(tag)
            _, _, domain = tag.partition(":")
            if domain:
                domain_tags.add(domain)
    return tuple(sorted(safety_signals)), tuple(sorted(domain_tags))


SENSITIVE_SIGNALS = {
    "password": "sensitive-domain:secrets",  # pragma: allowlist secret
    "secret": "sensitive-domain:secrets",  # pragma: allowlist secret
    "api_key": "sensitive-domain:secrets",  # pragma: allowlist secret
    "private_key": "sensitive-domain:secrets",  # pragma: allowlist secret
    "auth": "sensitive-domain:auth",
    "login": "sensitive-domain:auth",
    "token": "sensitive-domain:auth",
    "credit_card": "sensitive-domain:pii",
    "ssn": "sensitive-domain:pii",
    "cryptography": "sensitive-domain:crypto",
    "encrypt": "sensitive-domain:crypto",
    "decrypt": "sensitive-domain:crypto",
}
