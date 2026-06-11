"""Run invocation metadata for saved RevRem artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from code_review_loop import redaction

INVOCATION_SCHEMA_VERSION = "1.0"
SENSITIVE_ENV_NAME = re.compile(r"(TOKEN|SECRET|KEY|PASSWORD|PASS|CREDENTIAL|AUTH)", re.I)
CAPTURED_ENV_PREFIXES = ("REVREM_",)
SENSITIVE_CLI_FLAGS = {"--commit-message-prompt", "--triage-prompt"}


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False
    for item in argv:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if item in SENSITIVE_CLI_FLAGS:
            redacted.append(item)
            redact_next = True
            continue
        if any(item.startswith(f"{flag}=") for flag in SENSITIVE_CLI_FLAGS):
            flag, _sep, _value = item.partition("=")
            redacted.append(f"{flag}=<redacted>")
            continue
        redacted.append(redaction.redact_text(item).text)
    return tuple(redacted)


def invocation_payload(
    *,
    executable: str,
    argv: Sequence[str],
    cwd: Path,
    command_line: Sequence[str],
    environ: Mapping[str, str],
) -> dict[str, object]:
    return {
        "schema_version": INVOCATION_SCHEMA_VERSION,
        "argv": [redaction.redact_text(executable).text, *redact_argv(argv)],
        "command_line": list(command_line),
        "cwd": redaction.redact_text(str(cwd)).text,
        "environment": captured_environment(environ),
    }


def captured_environment(environ: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in sorted(environ):
        if not name.startswith(CAPTURED_ENV_PREFIXES):
            continue
        value = environ[name]
        values[name] = _redacted_env_value(name, value)
    return values


def _redacted_env_value(name: str, value: str) -> str:
    if SENSITIVE_ENV_NAME.search(name):
        return "[REDACTED:env-value]"
    return redaction.redact_text(value).text
