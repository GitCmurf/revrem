"""Harness metadata and command adapters for review/remediation backends."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

CODEX_MINIMAL_UNSUPPORTED_COMMIT_MODELS = frozenset({"gpt-5.3-codex-spark"})
CODEX_MINIMAL_UNSUPPORTED_ADJUSTMENT = "codex_minimal_unsupported_by_model"
REASONING_EFFORT_HARNESSES = frozenset({"codex"})
GEMINI_ARGV_PROMPT_MAX_BYTES = 100_000


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


@dataclass(frozen=True)
class ReasoningEffortResolution:
    effective: str | None
    requested: str | None
    adjustment: str | None = None


@dataclass(frozen=True)
class PromptInvocation:
    command: list[str]
    stdin: str | None
    delivery: str
    prompt_chars: int | None = None
    prompt_bytes: int | None = None
    prompt_artifact: Path | None = None

    def __iter__(self) -> Iterator[object]:
        # Preserve the historical `(command, stdin)` unpacking contract.
        yield self.command
        yield self.stdin


class HarnessAdapter(Protocol):
    def command(self, request: PhaseCommandRequest) -> list[str]: ...


def resolve_commit_message_reasoning_effort(
    *,
    harness: str,
    model: str | None,
    requested_effort: str | None,
) -> ReasoningEffortResolution:
    if (
        harness == "codex"
        and requested_effort == "minimal"
        and model in CODEX_MINIMAL_UNSUPPORTED_COMMIT_MODELS
    ):
        return ReasoningEffortResolution(
            effective="low",
            requested=requested_effort,
            adjustment=CODEX_MINIMAL_UNSUPPORTED_ADJUSTMENT,
        )
    return ReasoningEffortResolution(
        effective=requested_effort, requested=requested_effort
    )


def reasoning_effort_supported(harness: str) -> bool:
    """Return whether RevRem can enforce reasoning effort for this harness.

    The resolved phase config may carry a reasoning-effort value for every
    harness, but only adapters that map it into their provider argv should show
    it as an effective operator control.
    """
    return harness in REASONING_EFFORT_HARNESSES


def phase_effort_text(harness: str | None, effort: str | None) -> str | None:
    """Return the operator-facing effort text for a phase.

    Mirrors the prior ``_phase_effort_text`` helpers in ``runtime.py`` and
    ``tui_state.py``: unsupported harnesses are surfaced as ``"n/a"`` and a
    missing effort is ``None``. Both call sites should use this helper so the
    supported-harness set and the ``"n/a"`` literal stay in one place.
    """
    if not effort:
        return None
    if harness and not reasoning_effort_supported(harness):
        return "n/a"
    return effort


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
        if request.role == "commit-message":
            command.extend(["-c", 'web_search="disabled"'])
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
            command.extend(
                ["--output-last-message", str(request.output_last_message_path)]
            )
        command.append("-")
        return command


class ClaudeHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        command = [request.executable, "--print"]
        command.extend(_claude_permission_args(request))
        if request.model:
            command.extend(["--model", request.model])
        return command


class GeminiHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        # Prompt delivery is adapted later by prepare_prompt_invocation.
        command = [request.executable]
        command.extend(_gemini_permission_args(request))
        if request.model:
            command.extend(["--model", request.model])
        return command


OPENCODE_DEBUG_ENV = "REVREM_OPENCODE_DEBUG"
OPENCODE_DEBUG_ARGV: tuple[str, ...] = ("--print-logs", "--log-level", "INFO")


class OpenCodeHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        command = [request.executable, "run"]
        if os.environ.get(OPENCODE_DEBUG_ENV) == "1":
            # Best-effort operator aid. The argv values in
            # ``OPENCODE_DEBUG_ARGV`` are confirmed-valid against
            # ``opencode run --help`` and locked by
            # ``test_opencode_debug_argv_is_well_formed``. If a future
            # opencode release renames these flags, update the constant in
            # one place and re-run the suite.
            command.extend(OPENCODE_DEBUG_ARGV)
        command.extend(_opencode_permission_args(request))
        if request.model:
            command.extend(["--model", request.model])
        return command


class KiloHarnessAdapter(HarnessAdapter):
    def command(self, request: PhaseCommandRequest) -> list[str]:
        command = [request.executable, "run"]
        command.extend(_kilo_permission_args(request))
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
HARNESS_FIXTURES_DIR = ROOT / "tests" / "fixtures" / "harnesses"


def _codex_config_args(reasoning_effort: str | None) -> list[str]:
    if reasoning_effort is None:
        return []
    return ["-c", f'model_reasoning_effort="{reasoning_effort}"']


def _claude_permission_args(request: PhaseCommandRequest) -> list[str]:
    if request.sandbox == "read-only":
        return ["--permission-mode", "plan"]
    if request.full_auto:
        return ["--permission-mode", "auto"]
    return []


def _gemini_permission_args(request: PhaseCommandRequest) -> list[str]:
    if request.sandbox == "read-only":
        return ["--approval-mode", "plan"]
    if request.full_auto:
        return ["--approval-mode", "auto_edit"]
    return []


def _opencode_permission_args(request: PhaseCommandRequest) -> list[str]:
    if request.full_auto and request.sandbox == "workspace-write":
        return ["--dangerously-skip-permissions"]
    return []


def _kilo_permission_args(request: PhaseCommandRequest) -> list[str]:
    if request.full_auto and request.sandbox == "workspace-write":
        return ["--auto"]
    return []


PRODUCTION_HARNESS_REGISTRY = MappingProxyType(HARNESS_REGISTRY)
TEST_HARNESS_REGISTRY = MappingProxyType(
    {**HARNESS_REGISTRY, "fake": FAKE_HARNESS_SPEC}
)


def harness_registry() -> Mapping[str, HarnessSpec]:
    if fake_harness_enabled():
        return TEST_HARNESS_REGISTRY
    return PRODUCTION_HARNESS_REGISTRY


def validate_harness_name(name: str, *, field: str = "harness") -> None:
    registry = harness_registry()
    if name not in registry:
        known = ", ".join(sorted(registry.keys()))
        raise ValueError(f"{field} must be one of: {known}")


def require_implemented_harness(name: str, *, field: str = "harness") -> None:
    spec = harness_registry().get(name)
    if spec and not spec.implemented:
        raise ValueError(
            f"{field}={name!r} is valid profile syntax, but command execution is not implemented"
        )


def resolve_executable(
    harness: str,
    harness_executables: dict[str, str],
    codex_bin: str,
) -> str:
    if harness in harness_executables:
        return harness_executables[harness]
    if harness == "codex":
        return codex_bin
    registry = harness_registry()
    if harness in registry:
        return registry[harness].executable
    return harness


def build_phase_command(request: PhaseCommandRequest) -> list[str]:
    adapter = HARNESS_ADAPTERS.get(request.harness)
    if adapter is None:
        raise ValueError(f"unknown harness: {request.harness}")
    return adapter.command(request)


def prepare_prompt_invocation(
    harness: str,
    command: list[str],
    prompt: str | None,
    *,
    prompt_artifact_path: Path | None = None,
) -> PromptInvocation:
    """Adapt prompt delivery to each harness' non-interactive CLI contract."""
    if prompt is None:
        return PromptInvocation(list(command), None, "none")
    encoded = prompt.encode("utf-8")
    if harness == "opencode":
        if prompt_artifact_path is None:
            raise ValueError("opencode prompt delivery requires a prompt artifact path")
        adapted = list(command)
        adapted.append("Follow the attached RevRem prompt exactly.")
        adapted.extend(["--file", str(prompt_artifact_path)])
        return PromptInvocation(
            adapted,
            None,
            "file",
            prompt_chars=len(prompt),
            prompt_bytes=len(encoded),
            prompt_artifact=prompt_artifact_path,
        )
    if harness == "gemini":
        if len(encoded) > GEMINI_ARGV_PROMPT_MAX_BYTES:
            raise ValueError(
                "gemini prompt exceeds RevRem's current --prompt delivery cap "
                f"({len(encoded)} > {GEMINI_ARGV_PROMPT_MAX_BYTES} bytes); lower "
                "--external-review-input-chars or use another review harness"
            )
        adapted = list(command)
        adapted.extend(["--prompt", prompt])
        return PromptInvocation(
            adapted,
            None,
            "argv-prompt",
            prompt_chars=len(prompt),
            prompt_bytes=len(encoded),
        )
    return PromptInvocation(
        list(command),
        prompt,
        "stdin",
        prompt_chars=len(prompt),
        prompt_bytes=len(encoded),
    )


def harness_capabilities_payload(name: str) -> dict[str, Any]:
    spec = harness_registry().get(name)
    if spec is None or spec.capabilities is None:
        return {
            **asdict(
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
            ),
            "schema_version": "1.0",
            "contract_version": "1.0",
        }
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
    """Run the deterministic ``revrem-fake-harness`` script for tests.

    Note: the ``--scenario timeout`` branch returns ``(-1, "", ...)``.
    ``classify_provider_failure`` maps any negative return code to the
    ``provider_interrupted`` reason with ``transient=True`` (see
    ``provider_failures.classify_provider_failure``), and ``run_review_with_retry``
    treats that as a retryable signal. Operators wiring the fake harness into
    retry-counter tests will see two fake-harness invocations for one
    ``--scenario timeout`` call. Other scenarios (clear, findings,
    remediation_partial, etc.) use return code 0 or 2 and are not retried.
    """
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
        return (
            2,
            "",
            "REVREM_ALLOW_FAKE_HARNESS is enabled, but this scenario is unsupported\n",
        )

    fixture_dir = os.environ.get(FAKE_HARNESS_FIXTURE_ENV)
    base = (
        Path(fixture_dir) / scenario if fixture_dir else HARNESS_FIXTURES_DIR / scenario
    )

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
    if not is_fake_harness_command(args):
        return None
    scenario: str | None = None
    for index, arg in enumerate(args):
        if arg == "--scenario":
            if index + 1 >= len(args):
                return None
            scenario = args[index + 1]
            break
        if arg.startswith("--scenario="):
            scenario = arg.split("=", 1)[1]
            break
    if scenario is None:
        return None
    return FAKE_HARNESS_TOKEN_CHARGES.get(scenario)
