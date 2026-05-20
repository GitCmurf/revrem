"""Harness metadata for review/remediation backends.

The loop only executes Codex today, but profiles should not bake Codex-specific
shape into user configuration. This registry keeps validation and future command
construction decoupled.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


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
    cost_reporting: str  # "none", "tokens", "usd"
    supported_models: tuple[str, ...]


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
    output_last_message_path: Path | None = None


class HarnessAdapter(Protocol):
    def command(self, request: PhaseCommandRequest) -> list[str]: ...


class CodexHarnessAdapter(HarnessAdapter):
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
            and request.output_last_message_path is not None
        ):
            command.extend(["--output-last-message", str(request.output_last_message_path)])
        command.append("-")
        return command



class ClaudeHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        # Claude uses -p/--print
        # Assuming we pass prompt via stdin and use --print
        command = [request.executable, "--print"]
        if request.model:
            command.extend(["--model", request.model])
        return command

class GeminiHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        # Gemini uses -p/--prompt
        command = [request.executable, "--prompt"]
        if request.model:
            command.extend(["--model", request.model])
        return command

class OpenCodeHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        # OpenCode uses run
        command = [request.executable, "run"]
        if request.model:
            command.extend(["--model", request.model])
        return command

class KiloHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        # Kilo uses run
        command = [request.executable, "run"]
        if request.model:
            command.extend(["--model", request.model])
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
        implemented=True,
        notes="Headless non-interactive Claude CLI adapter.",
        capabilities=HarnessCapabilities(
            review_supported=True,
            remediation_supported=True,
            triage_supported=True,
            commit_message_supported=True,
            non_interactive=True,
            sandbox_modes=("read-only", "workspace-write"),
            timeout_supported=False,
            cancellation_supported=False,
            structured_output_supported=False,
            cost_reporting="none",
            supported_models=(),
        ),
    ),
    "gemini": HarnessSpec(
        name="gemini",
        executable="gemini",
        implemented=True,
        notes="Headless non-interactive Gemini CLI adapter.",
        capabilities=HarnessCapabilities(
            review_supported=True,
            remediation_supported=True,
            triage_supported=True,
            commit_message_supported=True,
            non_interactive=True,
            sandbox_modes=("read-only", "workspace-write"),
            timeout_supported=False,
            cancellation_supported=False,
            structured_output_supported=False,
            cost_reporting="none",
            supported_models=(),
        ),
    ),
    "opencode": HarnessSpec(
        name="opencode",
        executable="opencode",
        implemented=True,
        notes="Headless non-interactive OpenCode adapter.",
        capabilities=HarnessCapabilities(
            review_supported=True,
            remediation_supported=True,
            triage_supported=True,
            commit_message_supported=True,
            non_interactive=True,
            sandbox_modes=("read-only", "workspace-write"),
            timeout_supported=False,
            cancellation_supported=False,
            structured_output_supported=False,
            cost_reporting="none",
            supported_models=(),
        ),
    ),
    "kilo": HarnessSpec(
        name="kilo",
        executable="kilo",
        implemented=True,
        notes="Headless non-interactive Kilo adapter.",
        capabilities=HarnessCapabilities(
            review_supported=True,
            remediation_supported=True,
            triage_supported=True,
            commit_message_supported=True,
            non_interactive=True,
            sandbox_modes=("read-only", "workspace-write"),
            timeout_supported=False,
            cancellation_supported=False,
            structured_output_supported=False,
            cost_reporting="none",
            supported_models=(),
        ),
    ),
    "reserved": HarnessSpec(
        name="reserved",
        executable="reserved",
        implemented=False,
        notes="Reserved for testing unimplemented harness validation.",
    ),
}

FAKE_HARNESS_SPEC = HarnessSpec(
    name="fake",
    executable="fake",
    implemented=True,
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
    "claude": ClaudeHarnessAdapter(),
    "gemini": GeminiHarnessAdapter(),
    "opencode": OpenCodeHarnessAdapter(),
    "kilo": KiloHarnessAdapter(),
    "reserved": ReservedHarnessAdapter("reserved"),
    "fake": FakeHarnessAdapter(),
}


def fake_harness_enabled() -> bool:
    return os.environ.get("REVREM_ALLOW_FAKE_HARNESS") == "1"


FAKE_HARNESS_ENV = "REVREM_ALLOW_FAKE_HARNESS"
FAKE_HARNESS_FIXTURE_ENV = "REVREM_FAKE_HARNESS_FIXTURE_DIR"
FAKE_HARNESS_COMMAND = "revrem-fake-harness"

ROOT = Path(__file__).resolve().parents[2]
TRIAGE_SCHEMA_RESOURCE = "schemas/triage-v1.schema.json"
HARNESS_FIXTURES_DIR = ROOT / "tests" / "fixtures" / "harnesses"


def _codex_config_args(reasoning_effort: str | None) -> list[str]:
    if reasoning_effort is None:
        return []
    return ["-c", f'model_reasoning_effort="{reasoning_effort}"']


def harness_registry() -> dict[str, HarnessSpec]:
    registry = dict(HARNESS_REGISTRY)
    if fake_harness_enabled():
        registry["fake"] = FAKE_HARNESS_SPEC
    return registry


def validate_harness_name(name: str, *, field: str = "harness") -> None:
    if name not in harness_registry():
        known = ", ".join(sorted(harness_registry().keys()))
        raise ValueError(f"{field} must be one of: {known}")


def require_implemented_harness(name: str, *, field: str = "harness") -> None:
    spec = harness_registry().get(name)
    if spec and not spec.implemented:
        raise ValueError(
            f"{field}={name!r} is valid profile syntax, but only the codex backend is implemented"
        )



def build_phase_command(request: PhaseCommandRequest) -> list[str]:
    adapter = HARNESS_ADAPTERS.get(request.harness)
    if adapter is None:
        raise ValueError(f"unknown harness: {request.harness}")
    return adapter.command(request)


def harness_capabilities_payload(name: str) -> dict[str, Any]:
    spec = harness_registry().get(name)
    if spec is None or spec.capabilities is None:
        return asdict(
            HarnessCapabilities(
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
        )
    payload = asdict(spec.capabilities)
    # Ensure tuples are converted to lists for JSON schema validation
    if isinstance(payload.get("sandbox_modes"), tuple):
        payload["sandbox_modes"] = list(payload["sandbox_modes"])
    if isinstance(payload.get("supported_models"), tuple):
        payload["supported_models"] = list(payload["supported_models"])

    return {
        **payload,
        "schema_version": "1.0",
        "contract_version": "1.0",
    }


def run_fake_harness_command(args: list[str] | tuple[str, ...]) -> tuple[int, str, str]:
    if not fake_harness_enabled():
        return 2, "", f"ERROR: fake harness disabled; set {FAKE_HARNESS_ENV}=1\n"
    if len(args) < 2:
        return 1, "", "ERROR: too few arguments for fake harness\n"
    phase = args[1]
    scenario = "clear"
    for i, arg in enumerate(args):
        if arg == "--scenario" and i + 1 < len(args):
            scenario = args[i + 1]

    if scenario == "timeout":
        return -1, "", "Fake harness timeout\n"
    if scenario == "cancellation":
        raise KeyboardInterrupt()
    if scenario == "unsupported":
        return 2, "", "REVREM_ALLOW_FAKE_HARNESS is enabled, but this scenario is unsupported\n"

    fixture_dir = os.environ.get(FAKE_HARNESS_FIXTURE_ENV)
    base = Path(fixture_dir) / scenario if fixture_dir else HARNESS_FIXTURES_DIR / scenario

    # Use specialized filenames for each role
    if phase == "review":
        path = base / "review.txt"
    elif phase == "triage":
        path = base / "triage.txt"
    elif phase == "remediation":
        path = base / "remediation.txt"
    elif phase == "commit-message":
        path = base / "commit.txt"
    else:
        return 1, "", f"ERROR: unknown fake phase: {phase}\n"

    if not path.is_file():
        return 2, "", f"ERROR: fake harness fixture not found: {path}\n"

    if scenario == "remediation_partial":
        return 1, path.read_text(encoding="utf-8"), ""
    return 0, path.read_text(encoding="utf-8"), ""


def is_fake_harness_command(args: list[str] | tuple[str, ...]) -> bool:
    return bool(args and args[0] == FAKE_HARNESS_COMMAND)


FAKE_HARNESS_TOKEN_CHARGES = {
    "fake-findings": 5,
    "cost_ceiling": 10,
}


def fake_harness_token_charge(args: list[str] | tuple[str, ...]) -> int | None:
    if not is_fake_harness_command(args) or len(args) < 4:
        return None
    return FAKE_HARNESS_TOKEN_CHARGES.get(args[3])
