"""Harness metadata for review/remediation backends.

The loop only executes Codex today, but profiles should not bake Codex-specific
shape into user configuration. This registry keeps validation and future command
construction behind a small boundary.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

HARNESS_CAPABILITY_SCHEMA_VERSION = "1.0"
FAKE_HARNESS_ENV = "REVREM_ALLOW_FAKE_HARNESS"
FAKE_HARNESS_FIXTURE_ENV = "REVREM_FAKE_HARNESS_FIXTURE_DIR"
FAKE_HARNESS_COMMAND = "revrem-fake-harness"
FAKE_HARNESS_TOKEN_CHARGES = {
    "cost_charge": 10,
    "cost_ceiling": 10,
}
CostReporting = Literal["tokens", "usd", "none"]


@dataclass(frozen=True)
class HarnessCapabilities:
    review_supported: bool
    remediation_supported: bool
    triage_supported: bool
    commit_message_supported: bool
    non_interactive: bool
    sandbox_modes: tuple[str, ...]
    timeout_supported: bool
    cancellation_supported: bool
    structured_output_supported: bool
    cost_reporting: CostReporting
    supported_models: tuple[str, ...]
    contract_version: str = HARNESS_CAPABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema_version"] = HARNESS_CAPABILITY_SCHEMA_VERSION
        payload["sandbox_modes"] = list(self.sandbox_modes)
        payload["supported_models"] = list(self.supported_models)
        return cast(dict[str, object], payload)


@dataclass(frozen=True)
class HarnessSpec:
    name: str
    executable: str
    implemented: bool
    notes: str = ""
    capabilities: HarnessCapabilities | None = None


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


class FakeHarnessAdapter(HarnessAdapter):
    name = "fake"

    def command(self, request: PhaseCommandRequest) -> list[str]:
        if not fake_harness_enabled():
            raise NotImplementedError(
                f"harness {request.harness!r} is test-only and requires {FAKE_HARNESS_ENV}=1"
            )
        scenario = request.model or f"{request.role}_clear"
        return [FAKE_HARNESS_COMMAND, request.role, "--scenario", scenario]


HARNESS_REGISTRY: dict[str, HarnessSpec] = {
    "codex": HarnessSpec(
        name="codex",
        executable="codex",
        implemented=True,
        notes="Implemented review/remediation backend.",
        capabilities=HarnessCapabilities(
            review_supported=True,
            remediation_supported=True,
            triage_supported=True,
            commit_message_supported=True,
            non_interactive=True,
            sandbox_modes=("read-only", "workspace-write", "danger-full-access"),
            timeout_supported=True,
            cancellation_supported=True,
            structured_output_supported=False,
            cost_reporting="none",
            supported_models=(),
        ),
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

FAKE_HARNESS_SPEC = HarnessSpec(
    name="fake",
    executable="fake",
    implemented=False,
    notes="Test-only scripted harness; gated by REVREM_ALLOW_FAKE_HARNESS.",
    capabilities=HarnessCapabilities(
        review_supported=True,
        remediation_supported=True,
        triage_supported=True,
        commit_message_supported=True,
        non_interactive=True,
        sandbox_modes=("read-only", "workspace-write"),
        timeout_supported=True,
        cancellation_supported=True,
        structured_output_supported=True,
        cost_reporting="tokens",
        supported_models=("fake-clear", "fake-findings", "fake-timeout"),
    ),
)

HARNESS_ADAPTERS: dict[str, HarnessAdapter] = {
    "codex": CodexHarnessAdapter(),
    "claude": ReservedHarnessAdapter("claude"),
    "gemini": ReservedHarnessAdapter("gemini"),
    "opencode": ReservedHarnessAdapter("opencode"),
    "kilo": ReservedHarnessAdapter("kilo"),
    "fake": FakeHarnessAdapter(),
}


def fake_harness_enabled() -> bool:
    return os.environ.get(FAKE_HARNESS_ENV) == "1"


def harness_registry() -> dict[str, HarnessSpec]:
    if not fake_harness_enabled():
        return HARNESS_REGISTRY
    return {**HARNESS_REGISTRY, "fake": FAKE_HARNESS_SPEC}


def known_harness_names() -> tuple[str, ...]:
    return tuple(harness_registry())


def harness_capabilities(name: str) -> HarnessCapabilities:
    validate_harness_name(name, field="harness")
    spec = harness_registry()[name]
    if spec.capabilities is None:
        return HarnessCapabilities(
            review_supported=False,
            remediation_supported=False,
            triage_supported=False,
            commit_message_supported=False,
            non_interactive=False,
            sandbox_modes=(),
            timeout_supported=False,
            cancellation_supported=False,
            structured_output_supported=False,
            cost_reporting="none",
            supported_models=(),
        )
    return spec.capabilities


def harness_capabilities_payload(name: str) -> dict[str, object]:
    return harness_capabilities(name).to_dict()


def validate_harness_name(name: str, *, field: str) -> None:
    if name not in harness_registry():
        known = ", ".join(known_harness_names())
        raise ValueError(f"{field} must be one of: {known}")


def require_implemented_harness(name: str, *, field: str) -> None:
    validate_harness_name(name, field=field)
    spec = harness_registry()[name]
    if not spec.implemented:
        raise ValueError(
            f"{field}={name!r} is valid profile syntax, but only the codex backend is implemented"
        )


def build_phase_command(request: PhaseCommandRequest) -> list[str]:
    validate_harness_name(request.harness, field=f"{request.role}.harness")
    adapter = HARNESS_ADAPTERS.get(request.harness, ReservedHarnessAdapter(request.harness))
    return adapter.command(request)


def is_fake_harness_command(args: list[str] | tuple[str, ...]) -> bool:
    return bool(args) and args[0] == FAKE_HARNESS_COMMAND


def fake_harness_token_charge(args: list[str] | tuple[str, ...]) -> int | None:
    if len(args) != 4 or args[2] != "--scenario":
        return None
    return FAKE_HARNESS_TOKEN_CHARGES.get(args[3])


def run_fake_harness_command(args: list[str] | tuple[str, ...]) -> tuple[int, str, str]:
    if not fake_harness_enabled():
        return 2, "", f"{FAKE_HARNESS_ENV}=1 is required for the fake harness\n"
    if len(args) != 4 or args[2] != "--scenario":
        return 2, "", "usage: revrem-fake-harness <role> --scenario <scenario>\n"
    role = args[1]
    scenario = args[3]
    if scenario == "cancellation":
        raise KeyboardInterrupt
    if scenario == "timeout":
        return -1, "", "Fake harness timeout\n"
    if scenario == "unsupported":
        return 2, "", "Fake harness unsupported capability\n"
    fixture_dir = fake_harness_fixture_dir() / scenario
    output_path = fixture_dir / f"{role}.txt"
    if not output_path.is_file():
        return 2, "", f"fake harness fixture not found: {output_path}\n"
    return 0, output_path.read_text(encoding="utf-8"), ""


def fake_harness_fixture_dir() -> Path:
    configured = os.environ.get(FAKE_HARNESS_FIXTURE_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "harnesses"


def _codex_config_args(reasoning_effort: str | None) -> list[str]:
    if reasoning_effort is None:
        return []
    return ["-c", f'model_reasoning_effort="{reasoning_effort}"']
