"""Provider transcript observation helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping

from code_review_loop.core.ports import CommandResult

CODEX_BANNER_KEYS = {
    "workdir",
    "model",
    "provider",
    "approval",
    "sandbox",
    "reasoning effort",
    "reasoning summaries",
    "session id",
}


def codex_observation(
    result: CommandResult,
    *,
    phase: str,
    iteration: str,
    requested: Mapping[str, object],
) -> dict[str, object]:
    combined = _combined_output(result)
    observed = _parse_codex_banner(combined)
    observation: dict[str, object] = {
        "phase": phase,
        "iteration": iteration,
        "provider": "codex",
        "requested": dict(requested),
        "observed": observed,
        "raw_provider_finding_count": _raw_provider_finding_count(combined),
        "warnings": _observation_warnings(requested, observed),
    }
    command = _extract_timeout_command(combined)
    if command:
        observation["reported_command"] = command
    return observation


def _parse_codex_banner(output: str) -> dict[str, str]:
    observed: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line == "--------":
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key in CODEX_BANNER_KEYS:
            observed[key.replace(" ", "_")] = value.strip()
    return observed


def _observation_warnings(
    requested: Mapping[str, object],
    observed: Mapping[str, str],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    comparisons = {
        "model": "model",
        "sandbox": "sandbox",
        "reasoning_effort": "reasoning_effort",
    }
    for requested_key, observed_key in comparisons.items():
        requested_value = requested.get(requested_key)
        observed_value = observed.get(observed_key)
        if not isinstance(requested_value, str) or not observed_value:
            continue
        if requested_value == observed_value:
            continue
        warnings.append(
            {
                "kind": "provider_config_mismatch",
                "field": requested_key,
                "requested": requested_value,
                "observed": observed_value,
                "message": (
                    f"Provider observed {requested_key}={observed_value!r} "
                    f"but RevRem requested {requested_value!r}."
                ),
            }
        )
    return warnings


def _extract_timeout_command(output: str) -> str | None:
    match = re.search(r"(?m)^Command:\s+(.+)$", output)
    return match.group(1).strip() if match else None


def _raw_provider_finding_count(output: str) -> int:
    return len(re.findall(r'"type"\s*:\s*"finding"', output))


def _combined_output(result: CommandResult) -> str:
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return "\n".join(part for part in (stdout, stderr) if part)
