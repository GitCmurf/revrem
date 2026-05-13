"""Suppression file helpers for explicitly dismissed RevRem findings."""

from __future__ import annotations

import getpass
import json
import os
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from code_review_loop._compat_tomli_w import _escape_basic_string as _toml_escape_string

SUPPRESSION_SCHEMA_VERSION = "1.0"
SUPPRESSION_FILE_RELATIVE = Path(".revrem") / "suppressions.toml"
SUPPRESSION_AUDIT_RELATIVE = Path(".revrem") / "suppressions.audit.jsonl"
USER_SUPPRESSION_RELATIVE = Path(".config") / "revrem" / "suppressions.toml"
USER_AUDIT_RELATIVE = Path(".config") / "revrem" / "suppressions.audit.jsonl"
SEVERITIES = ("info", "low", "medium", "high", "critical")
SCOPES = ("repo", "user")
CRITICAL_MAX_EXPIRY_DAYS = 30


@dataclass(frozen=True)
class SuppressionEntry:
    fingerprint: str
    summary: str
    rationale: str
    created_at: str
    created_by: str
    scope: str
    severity_at_suppression: str
    expires_at: str | None = None
    critical_override: bool = False


@dataclass(frozen=True)
class SuppressionMatch:
    entry: SuppressionEntry
    source_path: Path


def repo_suppressions_path(cwd: Path) -> Path:
    return _repo_root(cwd) / SUPPRESSION_FILE_RELATIVE


def repo_audit_path(cwd: Path) -> Path:
    return _repo_root(cwd) / SUPPRESSION_AUDIT_RELATIVE


def user_suppressions_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / USER_SUPPRESSION_RELATIVE


def user_audit_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / USER_AUDIT_RELATIVE


def load_entries(path: Path) -> list[SuppressionEntry]:
    if not path.is_file():
        return []
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    values = raw.get("suppressions", [])
    if not isinstance(values, list):
        raise ValueError(f"{path}: suppressions must be an array of tables")
    return [entry_from_raw(item, path=path) for item in values]


def write_entries(path: Path, entries: list[SuppressionEntry]) -> None:
    from code_review_loop import artifacts

    path.parent.mkdir(parents=True, exist_ok=True)
    artifacts._atomic_write(path, render_entries(entries).encode("utf-8"))


def render_entries(entries: list[SuppressionEntry]) -> str:
    lines = [f"schema_version = {_toml_string(SUPPRESSION_SCHEMA_VERSION)}"]
    if not entries:
        lines.append("suppressions = []")
        return "\n".join(lines) + "\n"
    lines.append("")
    for index, entry in enumerate(entries):
        if index:
            lines.append("")
        lines.append("[[suppressions]]")
        for key, value in _entry_to_toml_dict(entry).items():
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines).rstrip() + "\n"


def entry_from_raw(raw: object, *, path: Path) -> SuppressionEntry:
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: suppression entry must be a table")
    fingerprint = _required_str(raw, "fingerprint", path)
    severity = _required_str(raw, "severity_at_suppression", path)
    if severity not in SEVERITIES:
        raise ValueError(f"{path}: severity_at_suppression must be one of {', '.join(SEVERITIES)}")
    scope = _required_str(raw, "scope", path)
    if scope not in SCOPES:
        raise ValueError(f"{path}: scope must be repo or user")
    critical_override = raw.get("critical_override", False)
    if not isinstance(critical_override, bool):
        raise ValueError(f"{path}: critical_override must be a boolean")
    expires_at = raw.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, str):
        raise ValueError(f"{path}: expires_at must be a string when present")
    entry = SuppressionEntry(
        fingerprint=fingerprint,
        summary=_required_str(raw, "summary", path),
        rationale=_required_str(raw, "rationale", path),
        created_at=_required_str(raw, "created_at", path),
        created_by=_required_str(raw, "created_by", path),
        scope=scope,
        severity_at_suppression=severity,
        expires_at=expires_at,
        critical_override=critical_override,
    )
    validate_entry(entry)
    return entry


def validate_entry(entry: SuppressionEntry) -> None:
    parse_timestamp(entry.created_at, field="created_at")
    if entry.expires_at is not None:
        parse_timestamp(entry.expires_at, field="expires_at")
    if entry.severity_at_suppression == "critical":
        if not entry.critical_override:
            raise ValueError("critical suppressions require critical_override=true")
        if entry.expires_at is None:
            raise ValueError("critical suppressions require expires_at")
        max_expires = parse_timestamp(entry.created_at, field="created_at") + timedelta(
            days=CRITICAL_MAX_EXPIRY_DAYS
        )
        if parse_timestamp(entry.expires_at, field="expires_at") > max_expires:
            raise ValueError(
                f"critical suppressions must expire within {CRITICAL_MAX_EXPIRY_DAYS} days"
            )


def parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def is_expired(entry: SuppressionEntry, *, now: datetime | None = None) -> bool:
    if entry.expires_at is None:
        return False
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise TypeError("now must be timezone-aware")
    return parse_timestamp(entry.expires_at, field="expires_at") <= current


def load_effective_suppressions(
    cwd: Path,
    *,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, SuppressionMatch]:
    effective: dict[str, SuppressionMatch] = {}
    for path in (user_suppressions_path(home), repo_suppressions_path(cwd)):
        for entry in load_entries(path):
            if is_expired(entry, now=now):
                continue
            # Repo entries are loaded second and intentionally win conflicts.
            effective[entry.fingerprint] = SuppressionMatch(entry=entry, source_path=path)
    return effective


def add_entry(
    path: Path,
    entry: SuppressionEntry,
    *,
    audit_path: Path | None = None,
) -> None:
    all_entries = load_entries(path)
    before = [asdict(item) for item in all_entries if item.fingerprint == entry.fingerprint]
    entries = [item for item in all_entries if item.fingerprint != entry.fingerprint]
    entries.append(entry)
    write_entries(path, sorted(entries, key=lambda item: item.fingerprint))
    append_audit(audit_path or default_audit_path_for(path), "add", before, [asdict(entry)])


def remove_entry(path: Path, fingerprint: str, *, audit_path: Path | None = None) -> bool:
    entries = load_entries(path)
    removed = [entry for entry in entries if entry.fingerprint == fingerprint]
    if not removed:
        return False
    write_entries(path, [entry for entry in entries if entry.fingerprint != fingerprint])
    append_audit(audit_path or default_audit_path_for(path), "remove", [asdict(item) for item in removed], [])
    return True


def expire_entries(path: Path, *, now: datetime | None = None, audit_path: Path | None = None) -> int:
    entries = load_entries(path)
    expired: list[SuppressionEntry] = []
    kept: list[SuppressionEntry] = []
    for entry in entries:
        (expired if is_expired(entry, now=now) else kept).append(entry)
    if not expired:
        return 0
    write_entries(path, kept)
    append_audit(audit_path or default_audit_path_for(path), "expire", [asdict(item) for item in expired], [])
    return len(expired)


def stale_entries(path: Path, *, now: datetime | None = None) -> tuple[list[SuppressionEntry], list[SuppressionEntry]]:
    expired: list[SuppressionEntry] = []
    unsupported: list[SuppressionEntry] = []
    for entry in load_entries(path):
        if is_expired(entry, now=now):
            expired.append(entry)
        if not entry.fingerprint.startswith("f1:"):
            unsupported.append(entry)
    return expired, unsupported


def audit_summary(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    counts: dict[str, int] = {}
    total = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                counts["invalid"] = counts.get("invalid", 0) + 1
                continue
        except json.JSONDecodeError:
            counts["invalid"] = counts.get("invalid", 0) + 1
            continue
        action = record.get("action")
        key = action if isinstance(action, str) and action else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return {"schema_version": SUPPRESSION_SCHEMA_VERSION, "total_records": total, "actions": counts}


def append_audit(path: Path, action: str, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": SUPPRESSION_SCHEMA_VERSION,
        "action": action,
        "timestamp": utc_now(),
        "actor": default_actor(),
        "before": before,
        "after": after,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def make_entry(
    *,
    fingerprint: str,
    summary: str,
    rationale: str,
    severity: str,
    scope: str,
    expires_at: str | None,
    critical_override: bool,
    created_by: str | None = None,
    created_at: str | None = None,
) -> SuppressionEntry:
    entry = SuppressionEntry(
        fingerprint=fingerprint,
        summary=summary,
        rationale=rationale,
        created_at=created_at or utc_now(),
        created_by=created_by or default_actor(),
        scope=scope,
        severity_at_suppression=severity,
        expires_at=expires_at,
        critical_override=critical_override,
    )
    validate_entry(entry)
    return entry


def apply_to_triage_payload(
    payload: dict[str, Any],
    matches: dict[str, SuppressionMatch],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    confirmed = payload.get("confirmed_findings", [])
    if not isinstance(confirmed, list):
        return payload, []
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for item in confirmed:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        fingerprint = item.get("fingerprint")
        match = matches.get(fingerprint) if isinstance(fingerprint, str) else None
        if match is None:
            kept.append(item)
            continue
        if item.get("severity") == "critical" and not match.entry.critical_override:
            kept.append(item)
            continue
        suppressed_item = {
            **item,
            "suppressed": True,
            "suppression": {
                "scope": match.entry.scope,
                "source_path": str(match.source_path),
                "summary": match.entry.summary,
                "rationale": match.entry.rationale,
                "expires_at": match.entry.expires_at,
            },
        }
        suppressed.append(suppressed_item)
    new_payload = {
        **payload,
        "confirmed_findings": kept,
        "suppressed_findings": suppressed,
        "implementation_order": [
            value
            for value in payload.get("implementation_order", [])
            if not any(
                isinstance(item, dict) and item.get("fingerprint") == value
                for item in suppressed
            )
        ],
    }
    return new_payload, suppressed


def default_actor() -> str:
    return os.environ.get("REVREM_SUPPRESSION_ACTOR") or getpass.getuser()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def default_audit_path_for(path: Path) -> Path:
    return path.with_name("suppressions.audit.jsonl")


def _entry_to_toml_dict(entry: SuppressionEntry) -> dict[str, object]:
    data: dict[str, object] = {
        "fingerprint": entry.fingerprint,
        "summary": entry.summary,
        "rationale": entry.rationale,
        "created_at": entry.created_at,
        "created_by": entry.created_by,
        "scope": entry.scope,
        "severity_at_suppression": entry.severity_at_suppression,
        "critical_override": entry.critical_override,
    }
    if entry.expires_at is not None:
        data["expires_at"] = entry.expires_at
    return data


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _toml_string(value)
    raise TypeError(f"unsupported suppression TOML value: {type(value).__name__}")


def _toml_string(value: str) -> str:
    return f'"{_toml_escape_string(value)}"'


def _required_str(raw: dict[str, object], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: {key} is required")
    return value


def _repo_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current
