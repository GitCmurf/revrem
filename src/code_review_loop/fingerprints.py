"""Stable finding fingerprint helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

FINGERPRINT_ALGORITHM = "f1"
SEVERITY_BUCKETS = {"info", "low", "medium", "high", "critical"}
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FindingFingerprintInput:
    rule_id: str | None
    path: str
    message: str
    severity: str


def finding_fingerprint(finding: FindingFingerprintInput) -> str:
    """Return the v1 stable fingerprint for a normalized finding."""
    components = (
        normalize_rule_id(finding.rule_id),
        normalize_path(finding.path),
        normalize_message_stem(finding.message),
        normalize_severity(finding.severity),
    )
    blob = "\x1f".join(components).encode("utf-8")
    return f"{FINGERPRINT_ALGORITHM}:" + hashlib.sha256(blob).hexdigest()[:16]


def normalize_rule_id(rule_id: str | None) -> str:
    if rule_id is None:
        return "<none>"
    normalized = _collapse_whitespace(rule_id)
    return normalized or "<none>"


def normalize_path(path: str) -> str:
    normalized = unicodedata.normalize("NFC", path).replace("\\", "/")
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
    return PurePosixPath(*parts).as_posix() if parts else "."


def normalize_message_stem(message: str) -> str:
    return _collapse_whitespace(message).lower()[:160]


def normalize_severity(severity: str) -> str:
    normalized = _collapse_whitespace(severity).lower()
    if normalized not in SEVERITY_BUCKETS:
        return "info"
    return normalized


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", value).strip())
