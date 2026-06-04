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

    if _has_any(normalized, ("authentication", "not authenticated", "login required", "api key")):
        return ProviderFailure("provider_auth_required", "provider auth/setup required", False)
    if _has_any(normalized, ("file not found:", "for more information, try '--help'", "unknown option", "invalid option", "you must provide a message or a command")):
        return ProviderFailure("provider_cli_contract_error", "provider CLI contract error", False)
    if (
        "quota_exhausted" in normalized
        or "terminalquotaerror" in normalized
        or "exhausted your capacity" in normalized
        or ("code: 429" in normalized and "quota" in normalized)
    ):
        return ProviderFailure("provider_quota_exhausted", "provider quota exhausted", False)
    if "unknownerror" in normalized or "unexpected server error" in normalized:
        ref = _extract_error_ref(output)
        suffix = f" ref={ref}" if ref else ""
        return ProviderFailure("provider_server_error", f"provider server error{suffix}", True)
    if _has_any(normalized, ("temporarily unavailable", "service unavailable", "connection reset", "econnreset", "timeout")):
        return ProviderFailure("provider_transient_error", "provider transient error", True)
    if "rate limit" in normalized or "too many requests" in normalized:
        return ProviderFailure("provider_rate_limited", "provider rate limited", True)
    if result.returncode < 0:
        return ProviderFailure("provider_interrupted", "provider subprocess interrupted", True)
    return None


def _combined_output(result: CommandResult) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _has_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


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
