"""Default redaction helpers for shareable RevRem diagnostics."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class RedactionFinding:
    category: str
    count: int


@dataclass(frozen=True)
class RedactionResult:
    text: str
    findings: tuple[RedactionFinding, ...]


@dataclass(frozen=True)
class RedactionRule:
    category: str
    pattern: re.Pattern[str]
    replacement: str


def redact_text(text: str, *, home: str | None = None, user: str | None = None) -> RedactionResult:
    """Redact common secret and local-identity patterns from text."""
    redacted = text
    counts: dict[str, int] = {}
    for rule in _rules(home=home, user=user):
        redacted, count = rule.pattern.subn(rule.replacement, redacted)
        if count:
            counts[rule.category] = counts.get(rule.category, 0) + count
    redacted, detected_count = _redact_detect_secrets_findings(redacted)
    if detected_count:
        counts["detect-secrets"] = counts.get("detect-secrets", 0) + detected_count
    return RedactionResult(
        text=redacted,
        findings=tuple(
            RedactionFinding(category=category, count=count)
            for category, count in sorted(counts.items())
        ),
    )


def redaction_summary(result: RedactionResult) -> dict[str, int]:
    return {finding.category: finding.count for finding in result.findings}


def _rules(*, home: str | None, user: str | None) -> tuple[RedactionRule, ...]:
    home_value = home if home is not None else os.environ.get("HOME")
    user_value = user if user is not None else os.environ.get("USER")
    rules = [
        RedactionRule(
            "private-key",
            re.compile(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL,
            ),
            "[REDACTED:private-key]",
        ),
        RedactionRule(
            "authorization-header",
            re.compile(r"(?im)^(\s*authorization\s*:\s*)(?!\s*\[REDACTED:)[^\r\n]+"),
            r"\1[REDACTED:authorization-header]",
        ),
        RedactionRule(
            "aws-access-key",
            re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
            "[REDACTED:aws-access-key]",
        ),
        RedactionRule(
            "github-token",
            re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}\b"),
            "[REDACTED:github-token]",
        ),
        RedactionRule(
            "anthropic-key",
            re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
            "[REDACTED:anthropic-key]",
        ),
        RedactionRule(
            "openai-key",
            re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}\b"),
            "[REDACTED:openai-key]",
        ),
        RedactionRule(
            "env-assignment",
            re.compile(
                r"(?im)^(\s*[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASS|CREDENTIAL)"
                r"[A-Z0-9_]*\s*=\s*)(?!\s*\[REDACTED:)[^\r\n]+"
            ),
            r"\1[REDACTED:env-assignment]",
        ),
        RedactionRule(
            "generic-token",
            re.compile(r"\b(?!\[REDACTED:)[A-Fa-f0-9]{32,}\b"),
            "[REDACTED:generic-token]",
        ),
    ]
    if home_value:
        rules.append(
            RedactionRule(
                "home-path",
                re.compile(re.escape(home_value)),
                "[REDACTED:home]",
            )
        )
    if user_value:
        rules.append(
            RedactionRule(
                "user",
                re.compile(rf"(?<![\w.-]){re.escape(user_value)}(?![\w.-])"),
                "[REDACTED:user]",
            )
        )
    return tuple(rules)


def _redact_detect_secrets_findings(text: str) -> tuple[str, int]:
    try:
        scan_module = import_module("detect_secrets.core.scan")
    except ModuleNotFoundError:
        return text, 0
    scan_line = getattr(scan_module, "scan_line", None)
    if scan_line is None:
        return text, 0

    redacted = text
    count = 0
    for line in text.splitlines():
        for secret in scan_line(line):
            secret_value = getattr(secret, "secret_value", None)
            if not isinstance(secret_value, str):
                continue
            if not secret_value or secret_value.startswith("[REDACTED:"):
                continue
            redacted, replacements = (
                redacted.replace(
                    secret_value,
                    "[REDACTED:detect-secrets]",
                ),
                redacted.count(secret_value),
            )
            count += replacements
    return redacted, count
