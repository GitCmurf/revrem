"""Provider subprocess failure classification."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from code_review_loop.core.ports import CommandResult


@dataclass(frozen=True)
class ProviderFailure:
    reason: str
    detail: str
    transient: bool


def classify_provider_failure(
    result: CommandResult,
    harness: str = "",
) -> ProviderFailure | None:
    """Classify a provider subprocess failure into a stable failure reason.

    The ``harness`` argument is currently unused for classification — the
    string matchers below are harness-agnostic. It is kept on the signature
    so harness-specific rules can be added in the future without a breaking
    API change for ``adapters/review.py`` and ``run_review_with_retry``.
    Callers must continue to pass ``config.review_harness`` for that
    forward compatibility.
    """
    del harness  # documented as a forward-compatibility hook
    if result.returncode == 0:
        return None
    output = _combined_output(result)
    normalized = output.lower()

    if result.returncode == -1 and "command timed out after" in normalized:
        return ProviderFailure(
            "provider_timeout", "provider subprocess timed out", False
        )
    if _matches_any(normalized, AUTH_PATTERNS):
        return ProviderFailure(
            "provider_auth_required", "provider auth/setup required", False
        )
    if _matches_any(normalized, CLI_CONTRACT_PATTERNS):
        return ProviderFailure(
            "provider_cli_contract_error", "provider CLI contract error", False
        )
    if _matches_any(normalized, QUOTA_PATTERNS):
        return ProviderFailure(
            "provider_quota_exhausted", "provider quota exhausted", False
        )
    if _matches_any(normalized, MODEL_UNAVAILABLE_PATTERNS):
        return ProviderFailure(
            "provider_model_unavailable", "provider model unavailable", False
        )
    if _matches_any(normalized, SERVER_ERROR_PATTERNS):
        ref = _extract_error_ref(output)
        suffix = f" ref={ref}" if ref else ""
        return ProviderFailure(
            "provider_server_error", f"provider server error{suffix}", True
        )
    if _matches_any(normalized, TRANSIENT_PATTERNS):
        return ProviderFailure(
            "provider_transient_error", "provider transient error", True
        )
    if _matches_any(normalized, RATE_LIMIT_PATTERNS):
        return ProviderFailure("provider_rate_limited", "provider rate limited", True)
    if result.returncode < 0:
        return ProviderFailure(
            "provider_interrupted", "provider subprocess interrupted", True
        )
    return None


def _combined_output(result: CommandResult) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) for pattern in patterns)


AUTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bauthentication\b"),
    re.compile(r"\bnot authenticated\b"),
    re.compile(r"\blogin required\b"),
    re.compile(r"\bapi key\b"),
)
CLI_CONTRACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"file not found:"),
    re.compile(r"for more information, try '--help'"),
    re.compile(r"\bunknown option\b"),
    re.compile(r"\binvalid option\b"),
    re.compile(r"you must provide a message or a command"),
)
QUOTA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bquota_exhausted\b"),
    re.compile(r"\bterminalquotaerror\b"),
    re.compile(r"\bexhausted your capacity\b"),
    re.compile(r"\bcode:\s*429\b.*\bquota\b"),
)
MODEL_UNAVAILABLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmodel not found\b"),
    re.compile(r"\bunknown model\b"),
    re.compile(r"\bunsupported model\b"),
    re.compile(r"\bdid you mean:\b"),
)
SERVER_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bunknownerror\b"),
    re.compile(r"\bunexpected server error\b"),
)
TRANSIENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bservice unavailable\b"),
    re.compile(r"\bconnection reset\b"),
    re.compile(r"\beconnreset\b"),
    re.compile(r"\bconnection refused\b"),
    re.compile(r"\bconnection timed out\b"),
    re.compile(r"\btimeout\b"),
    re.compile(r"\bnetwork is unreachable\b"),
)
RATE_LIMIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brate limit\b"),
    re.compile(r"\btoo many requests\b"),
)


def _extract_error_ref(output: str) -> str | None:
    match = re.search(r"\bref[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", output)
    if match:
        return match.group(1)
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        data = parsed.get("data")
        if isinstance(data, dict):
            ref = data.get("ref")
            if isinstance(ref, str):
                return ref
    return None
