"""Harness metadata for review/remediation backends.

The loop only executes Codex today, but profiles should not bake Codex-specific
shape into user configuration. This registry keeps validation and future command
construction behind a small boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HarnessSpec:
    name: str
    executable: str
    implemented: bool
    notes: str = ""


@dataclass(frozen=True)
class PhaseCommandRequest:
    harness: str
    role: str
    executable: str
    base: str = "main"
    model: str | None = None
    reasoning_effort: str | None = None
    sandbox: str = "workspace-write"
    color: str = "never"
    full_auto: bool = True
    json_output: bool = False
    output_last_message: bool = True
    output_last_message_path: Path | None = None


class HarnessAdapter:
    name: str

    def command(self, request: PhaseCommandRequest) -> list[str]:
        raise NotImplementedError


class CodexHarnessAdapter(HarnessAdapter):
    name = "codex"

    def command(self, request: PhaseCommandRequest) -> list[str]:
        if request.role == "review":
            return self._review_command(request)
        if request.role in {"remediation", "triage", "commit-message"}:
            return self._exec_command(request)
        raise ValueError(f"unsupported codex phase role: {request.role}")

    def _review_command(self, request: PhaseCommandRequest) -> list[str]:
        command = [request.executable]
        command.extend(_codex_config_args(request.reasoning_effort))
        if request.model:
            command.extend(["--model", request.model])
        command.extend(["review", "--base", request.base])
        return command

    def _exec_command(self, request: PhaseCommandRequest) -> list[str]:
        command = [request.executable, "exec"]
        command.extend(_codex_config_args(request.reasoning_effort))
        if request.role == "remediation" and request.full_auto:
            command.append("--full-auto")
        command.extend(["--sandbox", request.sandbox])
        command.extend(["--color", request.color])
        if request.json_output:
            command.append("--json")
        if request.model:
            command.extend(["--model", request.model])
        if (
            request.role == "remediation"
            and request.output_last_message
            and request.output_last_message_path is not None
        ):
            command.extend(["--output-last-message", str(request.output_last_message_path)])
        command.append("-")
        return command


class ReservedHarnessAdapter(HarnessAdapter):
    def __init__(self, name: str):
        self.name = name

    def command(self, request: PhaseCommandRequest) -> list[str]:
        raise NotImplementedError(
            f"harness {request.harness!r} is valid profile syntax, but command execution is not implemented"
        )


HARNESS_REGISTRY: dict[str, HarnessSpec] = {
    "codex": HarnessSpec(
        name="codex",
        executable="codex",
        implemented=True,
        notes="Implemented review/remediation backend.",
    ),
    "claude": HarnessSpec(
        name="claude",
        executable="claude",
        implemented=False,
        notes="Reserved for a future headless non-interactive Claude CLI adapter.",
    ),
    "gemini": HarnessSpec(
        name="gemini",
        executable="gemini",
        implemented=False,
        notes="Reserved for a future headless non-interactive Gemini CLI adapter.",
    ),
    "opencode": HarnessSpec(
        name="opencode",
        executable="opencode",
        implemented=False,
        notes="Reserved for a future headless non-interactive opencode adapter.",
    ),
    "kilo": HarnessSpec(
        name="kilo",
        executable="kilo",
        implemented=False,
        notes="Reserved for a future headless non-interactive Kilo adapter.",
    ),
}

HARNESS_ADAPTERS: dict[str, HarnessAdapter] = {
    "codex": CodexHarnessAdapter(),
    "claude": ReservedHarnessAdapter("claude"),
    "gemini": ReservedHarnessAdapter("gemini"),
    "opencode": ReservedHarnessAdapter("opencode"),
    "kilo": ReservedHarnessAdapter("kilo"),
}


def known_harness_names() -> tuple[str, ...]:
    return tuple(HARNESS_REGISTRY)


def validate_harness_name(name: str, *, field: str) -> None:
    if name not in HARNESS_REGISTRY:
        known = ", ".join(known_harness_names())
        raise ValueError(f"{field} must be one of: {known}")


def require_implemented_harness(name: str, *, field: str) -> None:
    validate_harness_name(name, field=field)
    spec = HARNESS_REGISTRY[name]
    if not spec.implemented:
        raise ValueError(
            f"{field}={name!r} is valid profile syntax, but only the codex backend is implemented"
        )


def build_phase_command(request: PhaseCommandRequest) -> list[str]:
    validate_harness_name(request.harness, field=f"{request.role}.harness")
    return HARNESS_ADAPTERS[request.harness].command(request)


def _codex_config_args(reasoning_effort: str | None) -> list[str]:
    if reasoning_effort is None:
        return []
    return ["-c", f'model_reasoning_effort="{reasoning_effort}"']
