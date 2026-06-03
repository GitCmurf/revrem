from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import harnesses, profiles
from code_review_loop.adapters import phase_support
from code_review_loop.adapters.subprocess_runner import default_runner
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import RunLoopFailed

LIVE_TIMEOUT_SECONDS = 120
LIVE_SMOKE_TOKEN = "REVREM_LIVE_SECONDARY_SMOKE_OK"
AUTH_SETUP_MARKERS = (
    "opening authentication page",
    "not authenticated",
    "login required",
    "authentication required",
    "please login",
    "please log in",
)


@dataclass(frozen=True)
class LiveProvider:
    name: str
    executable: str
    enable_env: str
    bin_env: str
    model_env: str


LIVE_PROVIDERS = {
    "claude": LiveProvider(
        name="claude",
        executable="claude",
        enable_env="REVREM_LIVE_CLAUDE",
        bin_env="REVREM_LIVE_CLAUDE_BIN",
        model_env="REVREM_LIVE_CLAUDE_MODEL",
    ),
    "gemini": LiveProvider(
        name="gemini",
        executable="gemini",
        enable_env="REVREM_LIVE_GEMINI",
        bin_env="REVREM_LIVE_GEMINI_BIN",
        model_env="REVREM_LIVE_GEMINI_MODEL",
    ),
    "opencode": LiveProvider(
        name="opencode",
        executable="opencode",
        enable_env="REVREM_LIVE_OPENCODE",
        bin_env="REVREM_LIVE_OPENCODE_BIN",
        model_env="REVREM_LIVE_OPENCODE_MODEL",
    ),
    "kilo": LiveProvider(
        name="kilo",
        executable="kilo",
        enable_env="REVREM_LIVE_KILO",
        bin_env="REVREM_LIVE_KILO_BIN",
        model_env="REVREM_LIVE_KILO_MODEL",
    ),
}


@dataclass(frozen=True)
class LiveProviderRuntime:
    executable: str
    model: str | None


def _configure_live_provider_environment(
    provider: LiveProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if provider.name == "gemini":
        monkeypatch.setenv(
            "GEMINI_CLI_TRUST_WORKSPACE",
            os.environ.get("GEMINI_CLI_TRUST_WORKSPACE", "true"),
        )


def _resolve_live_provider(provider: LiveProvider) -> LiveProviderRuntime:
    if os.environ.get(provider.enable_env) != "1":
        pytest.skip(
            f"set {provider.enable_env}=1 to run {provider.name} live smoke tests"
        )

    configured_executable = os.environ.get(provider.bin_env)
    executable = configured_executable or shutil.which(provider.executable)
    if executable is None:
        pytest.skip(
            f"{provider.executable!r} executable is not on PATH; set {provider.bin_env}"
        )
    if configured_executable:
        resolved = shutil.which(configured_executable)
        if resolved is not None:
            executable = resolved
        elif not Path(configured_executable).is_file():
            pytest.skip(
                f"{provider.bin_env}={configured_executable!r} is not executable on PATH "
                "or an existing file"
            )

    return LiveProviderRuntime(
        executable=executable,
        model=os.environ.get(provider.model_env),
    )


def _skip_if_provider_setup_missing(provider: LiveProvider, output: str) -> None:
    normalized = output.lower()
    if any(marker in normalized for marker in AUTH_SETUP_MARKERS):
        pytest.skip(
            f"{provider.name} live smoke requires an authenticated non-interactive CLI"
        )


@pytest.mark.parametrize("provider", LIVE_PROVIDERS.values(), ids=LIVE_PROVIDERS)
def test_live_secondary_provider_direct_smoke(
    provider: LiveProvider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_live_provider_environment(provider, monkeypatch)
    runtime = _resolve_live_provider(provider)
    prompt = (
        f"Print exactly this token and do not edit files: {LIVE_SMOKE_TOKEN}\n"
        "Do not include Markdown fences."
    )
    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=provider.name,
            role="remediation",
            executable=runtime.executable,
            model=runtime.model,
            sandbox="read-only",
            full_auto=False,
        )
    )
    prompt_path = None
    if provider.name == "opencode":
        prompt_path = tmp_path / "opencode-live-prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
    command, stdin = harnesses.prepare_prompt_invocation(
        provider.name,
        command,
        prompt,
        prompt_artifact_path=prompt_path,
    )

    result = default_runner(command, Path.cwd(), stdin, LIVE_TIMEOUT_SECONDS)
    output = phase_support._combined_output(result)
    _skip_if_provider_setup_missing(provider, output)

    assert result.returncode == 0, output
    assert LIVE_SMOKE_TOKEN in output


def test_live_routed_secondary_provider_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_name = os.environ.get("REVREM_LIVE_ROUTED_PROVIDER", "gemini")
    provider = LIVE_PROVIDERS.get(provider_name)
    if provider is None:
        known = ", ".join(sorted(LIVE_PROVIDERS))
        pytest.skip(f"REVREM_LIVE_ROUTED_PROVIDER must be one of: {known}")
    _configure_live_provider_environment(provider, monkeypatch)
    runtime = _resolve_live_provider(provider)

    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")

    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:live-secondary",
                "summary": "Confirm live secondary routed remediation",
                "severity": "low",
                "affected_paths": ["src/sample.py"],
                "rationale": "This live smoke verifies the selected secondary route executes.",
            }
        ],
        "rejected_findings": [],
        "needs_more_info": [],
        "implementation_order": ["f1:live-secondary"],
        "verification_commands": [],
        "parsing_warnings": [],
        "classification": {
            "domain_tags": ["harness"],
            "risk_level": "low",
            "refactor_depth": "atomic",
            "affected_modules": ["src/sample.py"],
            "estimated_blast_radius": {"module_count": 1, "finding_count": 1},
            "safety_signals": [],
            "failed_check_signals": [],
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": [
                f"The response includes {LIVE_SMOKE_TOKEN}.",
                "No files are edited.",
            ],
            "triage_prompt_draft": (
                f"Print exactly this token and do not edit files: {LIVE_SMOKE_TOKEN}"
            ),
        },
    }
    review_calls = 0

    def runner(
        args: Sequence[str],
        cwd: Path,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        nonlocal review_calls
        command = list(args)
        if command[:2] == ["revrem-fake-harness", "review"]:
            review_calls += 1
            scenario = "review_findings" if review_calls == 1 else "review_clear"
            return default_runner(
                ["revrem-fake-harness", "review", "--scenario", scenario],
                cwd,
                input_text,
                timeout_seconds,
            )
        if command == ["revrem-fake-harness", "triage", "--scenario", "triage_valid"]:
            return CommandResult(command, 0, stdout=json.dumps(triage_payload))
        return default_runner(command, cwd, input_text, timeout_seconds)

    profile = profiles.Profile(
        name="live-secondary-smoke",
        triage=profiles.TriageConfig(
            contract="v2",
            routing=profiles.TriageRoutingConfig(
                enabled=True,
                default_route="secondary",
            ),
            routes={
                "secondary": profiles.TriageRouteConfig(
                    harness=provider.name,
                    model=runtime.model,
                    timeout_seconds=LIVE_TIMEOUT_SECONDS,
                    sandbox="read-only",
                )
            },
        ),
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="review_findings",
        triage_harness="fake",
        triage_model="triage_valid",
        remediation_harness="fake",
        triage_enabled=True,
        triage_contract="v2",
        profile_v2=profile,
        harness_executables={provider.name: runtime.executable},
        check_commands=(),
        timeout_seconds=LIVE_TIMEOUT_SECONDS,
        remediation_timeout_seconds=LIVE_TIMEOUT_SECONDS,
        progress=False,
    )

    try:
        summary = runner_mod.run_loop(config, runner, terminal_ui=False).to_dict()
    except RunLoopFailed:
        remediation_artifact = config.artifact_dir / "remediation-1.txt"
        if remediation_artifact.is_file():
            _skip_if_provider_setup_missing(
                provider,
                remediation_artifact.read_text(encoding="utf-8"),
            )
        raise
    routing = json.loads(
        (config.artifact_dir / "routing-1.json").read_text(encoding="utf-8")
    )
    remediation_output = (config.artifact_dir / "remediation-1.txt").read_text(
        encoding="utf-8"
    )

    assert summary["final_status"] == "clear"
    assert routing["effective_route"]["harness"] == provider.name
    assert routing["effective_route"]["sandbox"] == "read-only"
    assert (config.artifact_dir / "routing-outcome-1.json").is_file()
    assert LIVE_SMOKE_TOKEN in remediation_output
    assert (tmp_path / "src" / "sample.py").read_text(encoding="utf-8") == "VALUE = 1\n"
