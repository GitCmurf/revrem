"""LoopConfig assembly + small CLI-argument resolution helpers (Wave C2a).

These functions translate ``argparse.Namespace`` + profile defaults into a
``LoopConfig`` for the thin CLI driver.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from code_review_loop import budgets, harnesses, profiles
from code_review_loop.cli.config_support import (
    current_git_state_for_latest,
    resolve_initial_review_file,
)
from code_review_loop.clock import SYSTEM_CLOCK, Clock
from code_review_loop.config import (
    DEFAULT_EXTERNAL_REVIEW_INPUT_CHARS,
    DEFAULT_EXTERNAL_REVIEW_TRUNCATION_POLICY,
    DEFAULT_EXTERNAL_REVIEW_WARNING_SECONDS,
    DEFAULT_GEMINI_PRO_REVIEW_INPUT_CHARS,
    DEFAULT_PROVIDER_RETRY_ATTEMPTS,
    DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    LoopConfig,
)
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity


def should_prompt_for_new_profile(args: argparse.Namespace) -> bool:
    if args.interactive is not None:
        return bool(args.interactive)
    return sys.stdin.isatty() and sys.stdout.isatty() and not args.description


def new_profile_from_args(args: argparse.Namespace) -> profiles.Profile:
    if should_prompt_for_new_profile(args):
        return profiles.prompt_for_new_profile(args.name)
    return profiles.minimal_profile(args.name, description=args.description)


def default_artifact_dir(
    *, clock: Clock = SYSTEM_CLOCK, identity: RunIdentity = SYSTEM_IDENTITY
) -> Path:
    timestamp = clock.now().strftime("%Y%m%dT%H%M%SZ")
    return Path(".revrem") / "runs" / f"{timestamp}-{identity.new_run_id()}"


def resolve_timeout_seconds(value: float) -> float | None:
    if value < 0:
        raise ValueError("--timeout-seconds must be 0 or greater")
    if value == 0:
        return None
    return value


def resolve_max_iterations(value: int) -> int:
    if value < 1:
        raise ValueError("--max-iterations must be at least 1")
    return value


def parse_harness_bin_overrides(values: Sequence[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--harness-bin must use HARNESS=EXECUTABLE syntax")
        harness, executable = value.split("=", 1)
        harness = harness.strip()
        executable = executable.strip()
        if not harness or not executable:
            raise ValueError("--harness-bin must use non-empty HARNESS=EXECUTABLE values")
        harnesses.validate_harness_name(harness, field="--harness-bin")
        overrides[harness] = executable
    return overrides


def resolve_profile_timeout_seconds(value: float | None) -> float | None:
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    if value < 0:
        raise ValueError("profile phase timeout must be non-negative")
    return value


def resolve_optional_timeout_seconds(value: float | None, *, flag: str) -> float | None:
    if value is None:
        return None
    if value < 0:
        raise ValueError(f"{flag} must be 0 or greater")
    if value == 0:
        return None
    return value


def _timeout_source(profile_source: str, *cli_values: object) -> str:
    return "cli" if any(value is not None for value in cli_values) else profile_source


def resolve_external_review_warning_seconds(value: float) -> float:
    if value < 0:
        raise ValueError("--external-review-warning-seconds must be 0 or greater")
    return value


def resolve_external_review_input_chars(
    *,
    args: argparse.Namespace,
    profile: profiles.Profile,
    profile_name: str | None,
    cwd: Path,
    review_harness: str,
    review_model: str | None,
    profile_source: str,
) -> tuple[int, str]:
    """Return (chars_limit, source_label) together to avoid duplicating the three-branch decision."""
    if args.external_review_input_chars is not None:
        val = int(args.external_review_input_chars)
        source = "cli"
    elif profile_runtime_key_explicit(profile_name, cwd, "external_review_input_chars"):
        val = profile.runtime.external_review_input_chars
        source = profile_source
    elif is_large_context_gemini_review_model(review_harness, review_model):
        val = DEFAULT_GEMINI_PRO_REVIEW_INPUT_CHARS
        source = "model-default"
    else:
        val = DEFAULT_EXTERNAL_REVIEW_INPUT_CHARS
        source = "defaults"

    if val is not None and val <= 0:
        raise ValueError("external_review_input_chars must be greater than 0")
    return val, source


_GEMINI_PRO_MODEL_PATTERN = re.compile(r"^gemini-\d+(?:\.\d+)*-pro(?:-[a-z0-9]+)*$")
# Multi-segment suffix scope: the optional ``(?:-[a-z0-9]+)*`` suffix
# accepts zero or more dash-separated segments (e.g. ``-preview``,
# ``-exp-03-25``, ``-exp-0827``). This ensures current and future Gemini
# Pro model names with multi-segment suffixes receive the large-context cap.


def is_large_context_gemini_review_model(
    review_harness: str,
    review_model: str | None,
) -> bool:
    model = (review_model or "").lower()
    if review_harness != "gemini" or not model.startswith("gemini-"):
        return False
    return _GEMINI_PRO_MODEL_PATTERN.match(model) is not None


def profile_runtime_key_explicit(
    profile_name: str | None,
    cwd: Path,
    key: str,
) -> bool:
    try:
        user_file, project_file = profiles.load_profile_files(cwd=cwd)
    except (OSError, ValueError):
        return False
    raw_sections: list[dict[str, object]] = []
    for profile_file in (user_file, project_file):
        if profile_file.raw_defaults:
            raw_sections.append(profile_file.raw_defaults)
        if profile_name and profile_name in profile_file.raw_profiles:
            raw_sections.append(profile_file.raw_profiles[profile_name])
    for raw in raw_sections:
        runtime = raw.get("runtime")
        if isinstance(runtime, dict) and key in runtime:
            return True
    return False


def profile_or_default(
    name: str | None,
    cwd: Path,
    *,
    require_implemented: bool = True,
) -> profiles.Profile:
    if name:
        return profiles.resolve_profile(name, cwd=cwd, require_implemented=require_implemented)
    return profiles.resolve_defaults(cwd=cwd, require_implemented=require_implemented)


def pick(cli_value, profile_value, fallback):
    if cli_value is not None:
        return cli_value
    if profile_value is not None:
        return profile_value
    return fallback


def _phase_source(profile_name: str | None, cli_override: object) -> str:
    if cli_override is not None:
        return "cli"
    return f"profile:{profile_name}" if profile_name else "defaults"


def _mixed_phase_source(field_sources: dict[str, str]) -> str:
    sources = set(field_sources.values())
    if len(sources) == 1:
        return next(iter(sources))
    return "mixed"


@dataclass(frozen=True)
class ResolvedPhaseConfig:
    harness: str
    model: str | None
    reasoning_effort: str | None
    timeout_seconds: float | None
    timeout_seconds_display: float | None
    field_sources: dict[str, str]


def _resolve_model_phase(
    *,
    phase_name: str,
    profile_name: str | None,
    profile_source: str,
    phase: profiles.PhaseConfig,
    harness_override: str | None,
    model_override: str | None,
    shared_model_override: str | None,
    reasoning_effort_override: str | None,
    shared_reasoning_effort_override: str | None,
    timeout_seconds: float | None,
    timeout_seconds_display: float | None,
    timeout_source: str,
) -> ResolvedPhaseConfig:
    harness = harness_override or phase.harness
    harnesses.validate_harness_name(harness, field=f"--{phase_name}-harness")
    model = model_override or shared_model_override or phase.model
    reasoning_effort = (
        reasoning_effort_override or shared_reasoning_effort_override or phase.reasoning_effort
    )
    return ResolvedPhaseConfig(
        harness=harness,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        timeout_seconds_display=timeout_seconds_display,
        field_sources={
            "harness": "cli" if harness_override else profile_source,
            "model": _phase_source(profile_name, model_override or shared_model_override),
            "reasoning_effort": _phase_source(
                profile_name,
                reasoning_effort_override or shared_reasoning_effort_override,
            ),
            "timeout_seconds": timeout_source,
        },
    )


def build_loop_config(
    args: argparse.Namespace,
    cwd: Path,
    *,
    require_implemented: bool = True,
) -> tuple[LoopConfig, str]:
    """Resolve a loop config from parsed CLI arguments.

    The wizard uses ``require_implemented=False`` so it can preview draft
    profiles without crashing on reserved harnesses.
    """

    try:
        profile = profile_or_default(
            args.profile,
            cwd,
            require_implemented=require_implemented,
        )
    except TypeError as exc:
        if "require_implemented" not in str(exc):
            raise
        profile = profile_or_default(args.profile, cwd)
    profile_source = f"profile:{args.profile}" if args.profile else "defaults"
    base = pick(args.base, profile.pipeline.base, "main")
    triage_enabled = pick(args.triage_enabled, profile.triage.enabled, False)
    triage_contract = pick(args.triage_contract, profile.triage.contract, "v1")
    routing_enabled = pick(args.routing_enabled, profile.triage.routing.enabled, False)
    routing_strict = pick(
        args.routing_strict,
        profile.triage.routing.strict_on_unavailable_route,
        True,
    )
    allow_model_escalation = pick(
        args.allow_model_escalation,
        profile.triage.routing.allow_model_escalation,
        True,
    )
    if routing_enabled and triage_contract != "v2":
        raise ValueError("--routing requires --triage-contract v2 or a v2 triage profile")
    if args.timeout_seconds is not None:
        timeout_seconds = resolve_timeout_seconds(args.timeout_seconds)
        review_timeout_seconds = timeout_seconds
        remediation_timeout_seconds = timeout_seconds
        triage_timeout_seconds = timeout_seconds if triage_enabled else None
        check_timeout_seconds = timeout_seconds
        timeout_seconds_display = args.timeout_seconds
        review_timeout_seconds_display = args.timeout_seconds
        remediation_timeout_seconds_display = args.timeout_seconds
        triage_timeout_seconds_display = args.timeout_seconds if triage_enabled else None
        check_timeout_seconds_display = args.timeout_seconds
    else:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        review_timeout_seconds = resolve_profile_timeout_seconds(profile.review.timeout_seconds)
        remediation_timeout_seconds = resolve_profile_timeout_seconds(
            profile.remediation.timeout_seconds
        )
        triage_timeout_seconds = (
            resolve_profile_timeout_seconds(profile.triage.timeout_seconds)
            if triage_enabled
            else None
        )
        check_timeout_seconds = timeout_seconds
        timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        review_timeout_seconds_display = profile.review.timeout_seconds
        if review_timeout_seconds_display is None:
            review_timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        remediation_timeout_seconds_display = profile.remediation.timeout_seconds
        if remediation_timeout_seconds_display is None:
            remediation_timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        triage_timeout_seconds_display = profile.triage.timeout_seconds if triage_enabled else None
        if triage_enabled and triage_timeout_seconds_display is None:
            triage_timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        check_timeout_seconds_display = timeout_seconds_display
    if args.review_timeout_seconds is not None:
        review_timeout_seconds = resolve_optional_timeout_seconds(
            args.review_timeout_seconds,
            flag="--review-timeout-seconds",
        )
        review_timeout_seconds_display = args.review_timeout_seconds
    if args.remediation_timeout_seconds is not None:
        remediation_timeout_seconds = resolve_optional_timeout_seconds(
            args.remediation_timeout_seconds,
            flag="--remediation-timeout-seconds",
        )
        remediation_timeout_seconds_display = args.remediation_timeout_seconds
    if args.triage_timeout_seconds is not None:
        triage_timeout_seconds = resolve_optional_timeout_seconds(
            args.triage_timeout_seconds,
            flag="--triage-timeout-seconds",
        )
        triage_timeout_seconds_display = args.triage_timeout_seconds
    if args.check_timeout_seconds is not None:
        check_timeout_seconds = resolve_optional_timeout_seconds(
            args.check_timeout_seconds,
            flag="--check-timeout-seconds",
        )
        check_timeout_seconds_display = args.check_timeout_seconds
    commit_after_remediation = (
        args.commit_after_remediation
        if args.commit_after_remediation is not None
        else profile.commit.enabled
    )
    artifact_dir_value = args.artifact_dir or profile.output.artifact_dir
    artifact_dir = Path(artifact_dir_value) if artifact_dir_value else default_artifact_dir()
    search_root = artifact_dir if artifact_dir_value else artifact_dir.parent
    current_git_state = (
        current_git_state_for_latest(cwd, base) if args.initial_review_file == "latest" else None
    )
    initial_review_file = resolve_initial_review_file(
        args.initial_review_file,
        search_root,
        current_git_state=current_git_state,
    )
    initial_review_mode = "explicit" if initial_review_file is not None else "none"
    if initial_review_file is not None and not initial_review_file.is_file():
        raise FileNotFoundError(f"initial review file not found: {initial_review_file}")
    checks = tuple(args.check) if args.check is not None else profile.pipeline.checks
    review_phase = _resolve_model_phase(
        phase_name="review",
        profile_name=args.profile,
        profile_source=profile_source,
        phase=profile.review,
        harness_override=args.review_harness,
        model_override=args.review_model,
        shared_model_override=args.model,
        reasoning_effort_override=args.review_reasoning_effort,
        shared_reasoning_effort_override=args.reasoning_effort,
        timeout_seconds=review_timeout_seconds,
        timeout_seconds_display=review_timeout_seconds_display,
        timeout_source=_timeout_source(
            profile_source,
            args.timeout_seconds,
            args.review_timeout_seconds,
        ),
    )
    remediation_phase = _resolve_model_phase(
        phase_name="remediation",
        profile_name=args.profile,
        profile_source=profile_source,
        phase=profile.remediation,
        harness_override=args.remediation_harness,
        model_override=args.remediation_model,
        shared_model_override=args.model,
        reasoning_effort_override=args.remediation_reasoning_effort,
        shared_reasoning_effort_override=args.reasoning_effort,
        timeout_seconds=remediation_timeout_seconds,
        timeout_seconds_display=remediation_timeout_seconds_display,
        timeout_source=_timeout_source(
            profile_source,
            args.timeout_seconds,
            args.remediation_timeout_seconds,
        ),
    )
    if not args.dry_run:
        harnesses.require_implemented_harness(review_phase.harness, field="review.harness")
        harnesses.require_implemented_harness(
            remediation_phase.harness,
            field="remediation.harness",
        )
    triage_reasoning_effort = args.triage_reasoning_effort or profile.triage.reasoning_effort
    triage_harness = args.triage_harness or profile.triage.harness
    harnesses.validate_harness_name(triage_harness, field="--triage-harness")
    if triage_enabled and not args.dry_run:
        harnesses.require_implemented_harness(triage_harness, field="triage.harness")
    commit_message_harness = args.commit_message_harness or profile.commit.harness
    harnesses.validate_harness_name(commit_message_harness, field="--commit-message-harness")
    if commit_after_remediation and not args.dry_run:
        harnesses.require_implemented_harness(commit_message_harness, field="commit.harness")
    triage_model = args.triage_model or profile.triage.model
    commit_reasoning_effort_inherited = (
        args.commit_reasoning_effort is None
        and profile.commit.reasoning_effort is None
        and remediation_phase.reasoning_effort is not None
    )
    commit_reasoning_effort = (
        args.commit_reasoning_effort
        or profile.commit.reasoning_effort
        or remediation_phase.reasoning_effort
    )
    commit_message_model = (
        args.commit_message_model
        or profile.commit.message_model
        or remediation_phase.model
        or args.model
        or review_phase.model
    )
    commit_effort_resolution = harnesses.resolve_commit_message_reasoning_effort(
        harness=commit_message_harness,
        model=commit_message_model,
        requested_effort=commit_reasoning_effort,
    )
    commit_reasoning_effort = commit_effort_resolution.effective
    commit_reasoning_effort_requested = commit_effort_resolution.requested
    commit_reasoning_effort_adjustment = commit_effort_resolution.adjustment
    commit_timeout_seconds = (
        resolve_optional_timeout_seconds(
            args.commit_timeout_seconds,
            flag="--commit-timeout-seconds",
        )
        if args.commit_timeout_seconds is not None
        else (
            resolve_profile_timeout_seconds(profile.commit.timeout_seconds)
            if profile.commit.timeout_seconds is not None
            else timeout_seconds
        )
    )
    commit_timeout_seconds_display = (
        args.commit_timeout_seconds
        if args.commit_timeout_seconds is not None
        else (
            profile.commit.timeout_seconds
            if profile.commit.timeout_seconds is not None
            else timeout_seconds_display
        )
    )
    commit_on_hook_failure = args.commit_on_hook_failure or profile.commit.on_hook_failure
    budget_config = budgets.BudgetConfig(
        max_wall_seconds=pick(args.max_wall_seconds, profile.budgets.max_wall_seconds, None),
        max_tokens=pick(args.max_tokens, profile.budgets.max_tokens, None),
        max_usd=(
            budgets.parse_usd(args.max_usd) if args.max_usd is not None else profile.budgets.max_usd
        ),
        soft_warn_fraction=pick(args.soft_warn_fraction, profile.budgets.soft_warn_fraction, 0.8),
    )
    budgets.validate_config(budget_config)
    harness_executables = {
        **profile.runtime.harness_executables,
        **parse_harness_bin_overrides(args.harness_bin),
    }
    max_iterations = pick(args.max_iterations, profile.pipeline.max_iterations, 2)
    max_iterations = resolve_max_iterations(max_iterations)
    routing = replace(
        profile.triage.routing,
        enabled=routing_enabled,
        strict_on_unavailable_route=routing_strict,
        allow_model_escalation=allow_model_escalation,
        default_route=args.routing_default_route or profile.triage.routing.default_route,
    )
    effective_triage = replace(
        profile.triage,
        enabled=triage_enabled,
        harness=triage_harness,
        model=triage_model,
        reasoning_effort=triage_reasoning_effort,
        timeout_seconds=triage_timeout_seconds,
        contract=triage_contract,
        routing=routing,
    )
    profile_v2 = replace(profile, triage=effective_triage)
    if (
        args.routing_default_route is not None
        and routing.default_route not in effective_triage.routes
    ):
        raise ValueError(f"--route refers to unknown route: {routing.default_route}")
    if routing.enabled and routing.default_route not in effective_triage.routes:
        raise ValueError(
            f"triage.routing.default_route refers to unknown route: {routing.default_route}"
        )
    external_review_input_chars, external_review_input_chars_source = (
        resolve_external_review_input_chars(
            args=args,
            profile=profile,
            profile_name=args.profile,
            cwd=cwd,
            review_harness=review_phase.harness,
            review_model=review_phase.model or args.model,
            profile_source=profile_source,
        )
    )
    external_review_warning_seconds_source = (
        "cli" if args.external_review_warning_seconds is not None
        else "profile" if profile.runtime.external_review_warning_seconds is not None
        else "default"
    )
    external_review_warning_seconds = resolve_external_review_warning_seconds(
        pick(
            args.external_review_warning_seconds,
            profile.runtime.external_review_warning_seconds,
            DEFAULT_EXTERNAL_REVIEW_WARNING_SECONDS,
        )
    )
    external_review_truncation_policy = pick(
        args.external_review_truncation_policy,
        profile.runtime.external_review_truncation_policy,
        DEFAULT_EXTERNAL_REVIEW_TRUNCATION_POLICY,
    )
    external_review_truncation_policy_source = (
        "cli" if args.external_review_truncation_policy is not None
        else "profile" if profile.runtime.external_review_truncation_policy is not None
        else "default"
    )
    inner_check_retries = int(
        pick(args.inner_check_retries, profile.runtime.inner_check_retries, 0)
    )
    if inner_check_retries < 0:
        raise ValueError("inner_check_retries must be 0 or greater")
    provider_retry_attempts = int(
        pick(
            args.provider_retry_attempts,
            profile.runtime.provider_retry_attempts,
            DEFAULT_PROVIDER_RETRY_ATTEMPTS,
        )
    )
    if provider_retry_attempts < 1:
        raise ValueError("provider_retry_attempts must be at least 1")
    provider_retry_backoff_seconds = float(
        pick(
            args.provider_retry_backoff_seconds,
            profile.runtime.provider_retry_backoff_seconds,
            DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS,
        )
    )
    if provider_retry_backoff_seconds < 0:
        raise ValueError("provider_retry_backoff_seconds must be 0 or greater")
    phase_config_field_sources = {
        "review": review_phase.field_sources,
        "triage": {
            "enabled": "cli" if args.triage_enabled is not None else profile_source,
            "harness": "cli" if args.triage_harness is not None else profile_source,
            "model": "cli" if args.triage_model is not None else profile_source,
            "reasoning_effort": (
                "cli" if args.triage_reasoning_effort is not None else profile_source
            ),
            "timeout_seconds": _timeout_source(
                profile_source,
                args.timeout_seconds,
                args.triage_timeout_seconds,
            ),
            "contract": "cli" if args.triage_contract is not None else profile_source,
            "routing_enabled": ("cli" if args.routing_enabled is not None else profile_source),
            "routing_strict": ("cli" if args.routing_strict is not None else profile_source),
            "routing_default_route": (
                "cli" if args.routing_default_route is not None else profile_source
            ),
            "allow_model_escalation": (
                "cli" if args.allow_model_escalation is not None else profile_source
            ),
        },
        "remediation": {
            **remediation_phase.field_sources,
            "sandbox": "cli" if args.exec_sandbox is not None else profile_source,
        },
        "commit_message": {
            "enabled": ("cli" if args.commit_after_remediation is not None else profile_source),
            "harness": ("cli" if args.commit_message_harness is not None else profile_source),
            "model": _phase_source(args.profile, args.commit_message_model or args.model),
            "reasoning_effort": (
                "cli"
                if args.commit_reasoning_effort is not None
                else "inherited:remediation"
                if commit_reasoning_effort_inherited
                else profile_source
            ),
            "timeout_seconds": _timeout_source(
                profile_source,
                args.timeout_seconds,
                args.commit_timeout_seconds,
            ),
        },
        "checks": {
            "commands": "cli" if args.check is not None else profile_source,
            "timeout_seconds": _timeout_source(
                profile_source,
                args.timeout_seconds,
                args.check_timeout_seconds,
            ),
        },
        "runtime": {
            "inner_check_retries": (
                "cli" if args.inner_check_retries is not None else profile_source
            ),
            "provider_retry_attempts": (
                "cli" if args.provider_retry_attempts is not None else profile_source
            ),
            "provider_retry_backoff_seconds": (
                "cli" if args.provider_retry_backoff_seconds is not None else profile_source
            ),
            "external_review_input_chars": external_review_input_chars_source,
            "external_review_warning_seconds": external_review_warning_seconds_source,
            "external_review_truncation_policy": external_review_truncation_policy_source,
        },
    }
    config = LoopConfig(
        base=base,
        max_iterations=max_iterations,
        codex_bin=pick(args.codex_bin, profile.runtime.codex_bin, "codex"),
        harness_executables=harness_executables,
        cwd=cwd,
        artifact_dir=artifact_dir,
        preflight_enabled=True,
        artifact_dir_is_default=artifact_dir_value is None,
        model=args.model,
        review_harness=review_phase.harness,
        remediation_harness=remediation_phase.harness,
        triage_harness=triage_harness,
        commit_message_harness=commit_message_harness,
        review_model=review_phase.model,
        remediation_model=remediation_phase.model,
        reasoning_effort=args.reasoning_effort,
        review_reasoning_effort=review_phase.reasoning_effort,
        remediation_reasoning_effort=remediation_phase.reasoning_effort,
        commit_after_remediation=commit_after_remediation,
        commit_message_model=commit_message_model,
        commit_message_prompt=args.commit_message_prompt or profile.commit.message_prompt,
        commit_message_prompt_overridden=(
            args.commit_message_prompt is not None or profile.commit.message_prompt is not None
        ),
        commit_on_hook_failure=commit_on_hook_failure,
        commit_reasoning_effort=commit_reasoning_effort,
        commit_reasoning_effort_requested=commit_reasoning_effort_requested,
        commit_reasoning_effort_adjustment=commit_reasoning_effort_adjustment,
        commit_timeout_seconds=commit_timeout_seconds,
        commit_timeout_seconds_display=commit_timeout_seconds_display,
        triage_enabled=triage_enabled,
        triage_model=triage_model,
        triage_reasoning_effort=triage_reasoning_effort,
        triage_timeout_seconds=triage_timeout_seconds,
        triage_prompt=profile.triage.prompt,
        triage_on_invalid=profile.triage.on_invalid,
        triage_contract=triage_contract,
        exec_sandbox=pick(args.exec_sandbox, profile.runtime.exec_sandbox, "workspace-write"),
        exec_color=pick(args.exec_color, profile.runtime.exec_color, "never"),
        full_auto=pick(args.full_auto, profile.runtime.full_auto, True),
        exec_json=pick(args.exec_json, profile.runtime.exec_json, False),
        output_last_message=pick(
            args.output_last_message, profile.runtime.output_last_message, True
        ),
        dry_run=args.dry_run,
        final_review=pick(args.final_review, profile.pipeline.final_review, True),
        max_remediation_input_chars=pick(
            args.max_remediation_input_chars,
            profile.runtime.max_remediation_input_chars,
            200_000,
        ),
        inner_check_retries=inner_check_retries,
        provider_retry_attempts=provider_retry_attempts,
        provider_retry_backoff_seconds=provider_retry_backoff_seconds,
        external_review_input_chars=external_review_input_chars,
        external_review_warning_seconds=external_review_warning_seconds,
        external_review_truncation_policy=external_review_truncation_policy,
        terminal_excerpt_chars=pick(
            args.terminal_excerpt_chars,
            profile.runtime.terminal_excerpt_chars,
            4_000,
        ),
        timeout_seconds=timeout_seconds,
        review_timeout_seconds=review_phase.timeout_seconds,
        remediation_timeout_seconds=remediation_phase.timeout_seconds,
        check_timeout_seconds=check_timeout_seconds,
        timeout_seconds_display=timeout_seconds_display,
        review_timeout_seconds_display=review_phase.timeout_seconds_display,
        remediation_timeout_seconds_display=remediation_phase.timeout_seconds_display,
        triage_timeout_seconds_display=triage_timeout_seconds_display,
        check_timeout_seconds_display=check_timeout_seconds_display,
        phase_config_sources={
            phase: _mixed_phase_source(sources)
            for phase, sources in phase_config_field_sources.items()
        },
        phase_config_field_sources=phase_config_field_sources,
        debug_status_detection=pick(
            args.debug_status_detection,
            profile.output.debug_status_detection,
            False,
        ),
        progress=not pick(args.quiet_progress, profile.output.quiet_progress, False),
        progress_style=pick(args.progress_style, profile.output.progress_style, "compact"),
        terminal_title=pick(args.terminal_title, profile.output.terminal_title, False),
        initial_review_file=initial_review_file,
        initial_review_mode=initial_review_mode,
        check_commands=checks,
        profile_name=args.profile,
        budget_config=budget_config,
        trusted_repo=pick(getattr(args, "trusted_repo", None), False, False),
        profile_v2=profile_v2,
    )
    return config, (args.summary_format or profile.output.summary_format)


def profile_from_loop_config(
    name: str,
    config: LoopConfig,
    *,
    summary_format: str,
    description: str = "",
    include_artifact_dir: bool = False,
    timeout_seconds: float | None = None,
) -> profiles.Profile:
    saved_timeout_seconds = (
        timeout_seconds if timeout_seconds is not None else config.review_timeout_seconds_display
    )
    saved_remediation_timeout_seconds = (
        timeout_seconds if timeout_seconds is not None else config.remediation_timeout_seconds_display
    )
    saved_triage_timeout_seconds = (
        timeout_seconds
        if timeout_seconds is not None and config.triage_enabled
        else config.triage_timeout_seconds_display
    )
    return profiles.Profile(
        name=name,
        description=description,
        pipeline=profiles.PipelineConfig(
            base=config.base,
            max_iterations=config.max_iterations,
            final_review=config.final_review,
            checks=config.check_commands,
        ),
        review=profiles.PhaseConfig(
            harness=config.review_harness,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
            timeout_seconds=saved_timeout_seconds,
        ),
        triage=profiles.TriageConfig(
            enabled=config.triage_enabled,
            harness=config.triage_harness,
            model=config.triage_model,
            reasoning_effort=config.triage_reasoning_effort,
            timeout_seconds=saved_triage_timeout_seconds,
            prompt=config.triage_prompt,
            on_invalid=config.triage_on_invalid,
            contract=config.triage_contract,
            routing=(
                config.profile_v2.triage.routing
                if config.profile_v2 is not None
                else profiles.TriageRoutingConfig()
            ),
            routes=(dict(config.profile_v2.triage.routes) if config.profile_v2 is not None else {}),
        ),
        remediation=profiles.PhaseConfig(
            harness=config.remediation_harness,
            model=config.remediation_model or config.model,
            reasoning_effort=config.remediation_reasoning_effort or config.reasoning_effort,
            timeout_seconds=saved_remediation_timeout_seconds,
        ),
        commit=profiles.CommitConfig(
            enabled=config.commit_after_remediation,
            harness=config.commit_message_harness,
            message_model=config.commit_message_model,
            message_prompt=config.commit_message_prompt,
            on_hook_failure=config.commit_on_hook_failure,
            reasoning_effort=config.commit_reasoning_effort,
            timeout_seconds=(
                config.commit_timeout_seconds_display if config.commit_after_remediation else None
            ),
        ),
        output=profiles.OutputConfig(
            summary_format=summary_format,
            debug_status_detection=config.debug_status_detection,
            progress_style=config.progress_style,
            quiet_progress=not config.progress,
            terminal_title=config.terminal_title,
            artifact_dir=str(config.artifact_dir) if include_artifact_dir else None,
        ),
        runtime=profiles.RuntimeConfig(
            codex_bin=config.codex_bin,
            harness_executables=dict(config.harness_executables),
            exec_sandbox=config.exec_sandbox,
            exec_color=config.exec_color,
            exec_json=config.exec_json,
            output_last_message=config.output_last_message,
            full_auto=config.full_auto,
            max_remediation_input_chars=config.max_remediation_input_chars,
            inner_check_retries=config.inner_check_retries,
            provider_retry_attempts=config.provider_retry_attempts,
            provider_retry_backoff_seconds=config.provider_retry_backoff_seconds,
            external_review_input_chars=config.external_review_input_chars,
            external_review_warning_seconds=config.external_review_warning_seconds,
            external_review_truncation_policy=config.external_review_truncation_policy,
            terminal_excerpt_chars=config.terminal_excerpt_chars,
        ),
        budgets=profiles.BudgetConfig(
            max_wall_seconds=config.budget_config.max_wall_seconds,
            max_tokens=config.budget_config.max_tokens,
            max_usd=config.budget_config.max_usd,
            soft_warn_fraction=config.budget_config.soft_warn_fraction,
        ),
    )
