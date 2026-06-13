"""Loop configuration public surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from code_review_loop import budgets, profiles

DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_EXTERNAL_REVIEW_INPUT_CHARS = 80_000
DEFAULT_GEMINI_PRO_REVIEW_INPUT_CHARS = 95_000
DEFAULT_EXTERNAL_REVIEW_WARNING_SECONDS = 1_800
EXTERNAL_REVIEW_TRUNCATION_POLICIES = ("warn", "fail")
DEFAULT_EXTERNAL_REVIEW_TRUNCATION_POLICY = "warn"
DEFAULT_PROVIDER_RETRY_ATTEMPTS = 2
DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class LoopConfig:
    base: str = "main"
    max_iterations: int = 1
    codex_bin: str = "codex"
    harness_executables: dict[str, str] = field(default_factory=dict)
    cwd: Path = field(default_factory=Path.cwd)
    artifact_dir: Path = field(default_factory=Path.cwd)
    preflight_enabled: bool = False
    artifact_dir_is_default: bool = False
    model: str | None = None
    review_harness: str = "codex"
    remediation_harness: str = "codex"
    triage_harness: str = "codex"
    commit_message_harness: str = "codex"
    review_model: str | None = None
    remediation_model: str | None = None
    reasoning_effort: str | None = None
    review_reasoning_effort: str | None = None
    remediation_reasoning_effort: str | None = None
    commit_after_remediation: bool = False
    commit_message_model: str | None = None
    commit_message_prompt: str | None = None
    commit_message_prompt_overridden: bool = False
    commit_on_hook_failure: str = "remediate"
    commit_reasoning_effort: str | None = None
    commit_reasoning_effort_requested: str | None = None
    commit_reasoning_effort_adjustment: str | None = None
    commit_timeout_seconds: float | None = None
    triage_enabled: bool = False
    triage_model: str | None = None
    triage_reasoning_effort: str | None = None
    triage_timeout_seconds: float | None = None
    triage_prompt: str | None = None
    triage_on_invalid: str = "continue"
    suppressions_enabled: bool = True
    exec_sandbox: str = "workspace-write"
    exec_color: str = "never"
    full_auto: bool = True
    exec_json: bool = False
    output_last_message: bool = True
    dry_run: bool = False
    final_review: bool = True
    max_remediation_input_chars: int = 200_000
    inner_check_retries: int = 0
    provider_retry_attempts: int = DEFAULT_PROVIDER_RETRY_ATTEMPTS
    provider_retry_backoff_seconds: float = DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS
    external_review_input_chars: int = DEFAULT_EXTERNAL_REVIEW_INPUT_CHARS
    external_review_warning_seconds: float = DEFAULT_EXTERNAL_REVIEW_WARNING_SECONDS
    external_review_truncation_policy: str = DEFAULT_EXTERNAL_REVIEW_TRUNCATION_POLICY
    terminal_excerpt_chars: int = 4_000
    timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS
    review_timeout_seconds: float | None = None
    remediation_timeout_seconds: float | None = None
    timeout_seconds_display: float | None = DEFAULT_TIMEOUT_SECONDS
    review_timeout_seconds_display: float | None = None
    remediation_timeout_seconds_display: float | None = None
    triage_timeout_seconds_display: float | None = None
    commit_timeout_seconds_display: float | None = None
    phase_config_sources: dict[str, str] = field(default_factory=dict)
    phase_config_field_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    debug_status_detection: bool = False
    progress: bool = True
    progress_style: str = "compact"
    terminal_title: bool = False
    initial_review_file: Path | None = None
    initial_review_mode: str = "none"
    check_commands: tuple[str, ...] = field(default_factory=tuple)
    profile_name: str | None = None
    budget_config: budgets.BudgetConfig = field(default_factory=budgets.BudgetConfig)
    profile_v2: profiles.Profile | None = None
    trusted_repo: bool = False
    triage_contract: str = "v1"
    command_line: tuple[str, ...] = field(default_factory=tuple)
    invocation: dict[str, object] = field(default_factory=dict)
