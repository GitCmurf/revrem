"""LoopConfig assembly + small CLI-argument resolution helpers (Wave C2a).

These functions translate ``argparse.Namespace`` + profile defaults into a
``LoopConfig`` for the thin CLI driver.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from code_review_loop import budgets, harnesses, profiles
from code_review_loop.cli.config_support import (
    resolve_initial_review_file,
)
from code_review_loop.clock import SYSTEM_CLOCK, Clock
from code_review_loop.config import DEFAULT_TIMEOUT_SECONDS, LoopConfig
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


def build_loop_config(args: argparse.Namespace, cwd: Path) -> tuple[LoopConfig, str]:
    profile = profile_or_default(args.profile, cwd)
    profile_source = f"profile:{args.profile}" if args.profile else "defaults"
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
        timeout_seconds_display = args.timeout_seconds
        review_timeout_seconds_display = args.timeout_seconds
        remediation_timeout_seconds_display = args.timeout_seconds
        triage_timeout_seconds_display = args.timeout_seconds if triage_enabled else None
    else:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        review_timeout_seconds = resolve_profile_timeout_seconds(profile.review.timeout_seconds)
        remediation_timeout_seconds = resolve_profile_timeout_seconds(profile.remediation.timeout_seconds)
        triage_timeout_seconds = (
            resolve_profile_timeout_seconds(profile.triage.timeout_seconds)
            if triage_enabled
            else None
        )
        timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        review_timeout_seconds_display = profile.review.timeout_seconds
        if review_timeout_seconds_display is None:
            review_timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        remediation_timeout_seconds_display = profile.remediation.timeout_seconds
        if remediation_timeout_seconds_display is None:
            remediation_timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
        triage_timeout_seconds_display = (
            profile.triage.timeout_seconds
            if triage_enabled
            else None
        )
        if triage_enabled and triage_timeout_seconds_display is None:
            triage_timeout_seconds_display = DEFAULT_TIMEOUT_SECONDS
    if args.triage_timeout_seconds is not None:
        triage_timeout_seconds = resolve_optional_timeout_seconds(
            args.triage_timeout_seconds,
            flag="--triage-timeout-seconds",
        )
        triage_timeout_seconds_display = args.triage_timeout_seconds
    commit_after_remediation = (
        args.commit_after_remediation
        if args.commit_after_remediation is not None
        else profile.commit.enabled
    )
    artifact_dir_value = args.artifact_dir or profile.output.artifact_dir
    artifact_dir = Path(artifact_dir_value) if artifact_dir_value else default_artifact_dir()
    search_root = artifact_dir if artifact_dir_value else artifact_dir.parent
    initial_review_file = resolve_initial_review_file(args.initial_review_file, search_root)
    if initial_review_file is not None and not initial_review_file.is_file():
        raise FileNotFoundError(f"initial review file not found: {initial_review_file}")
    checks = tuple(args.check) if args.check is not None else profile.pipeline.checks
    review_reasoning_effort = (
        args.review_reasoning_effort
        or args.reasoning_effort
        or profile.review.reasoning_effort
    )
    remediation_reasoning_effort = (
        args.remediation_reasoning_effort
        or args.reasoning_effort
        or profile.remediation.reasoning_effort
    )
    triage_reasoning_effort = args.triage_reasoning_effort or profile.triage.reasoning_effort
    triage_harness = args.triage_harness or profile.triage.harness
    harnesses.validate_harness_name(triage_harness, field="--triage-harness")
    commit_message_harness = args.commit_message_harness or profile.commit.harness
    harnesses.validate_harness_name(commit_message_harness, field="--commit-message-harness")
    if commit_after_remediation and not args.dry_run:
        harnesses.require_implemented_harness(commit_message_harness, field="commit.harness")
    triage_model = args.triage_model or profile.triage.model
    commit_reasoning_effort = (
        args.commit_reasoning_effort
        or profile.commit.reasoning_effort
        or remediation_reasoning_effort
    )
    if commit_message_harness == "codex" and commit_reasoning_effort == "minimal":
        # Codex 0.135.0 still injects built-in tools that are incompatible with
        # minimal reasoning. Commit-message drafting is cheap but quality
        # sensitive, so use the lowest live-compatible effort instead.
        commit_reasoning_effort = "low"
    commit_timeout_seconds = profile.commit.timeout_seconds
    commit_timeout_seconds_display = (
        profile.commit.timeout_seconds
        if profile.commit.timeout_seconds is not None
        else timeout_seconds_display
    )
    review_model = args.review_model or args.model or profile.review.model
    remediation_model = args.remediation_model or args.model or profile.remediation.model
    commit_message_model = (
        args.commit_message_model
        or profile.commit.message_model
        or remediation_model
        or args.model
        or review_model
    )
    commit_on_hook_failure = args.commit_on_hook_failure or profile.commit.on_hook_failure
    budget_config = budgets.BudgetConfig(
        max_wall_seconds=pick(args.max_wall_seconds, profile.budgets.max_wall_seconds, None),
        max_tokens=pick(args.max_tokens, profile.budgets.max_tokens, None),
        max_usd=budgets.parse_usd(args.max_usd) if args.max_usd is not None else profile.budgets.max_usd,
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
    )
    effective_triage = replace(
        profile.triage,
        enabled=triage_enabled,
        harness=triage_harness,
        model=triage_model,
        timeout_seconds=triage_timeout_seconds,
        contract=triage_contract,
        routing=routing,
    )
    profile_v2 = replace(profile, triage=effective_triage)
    phase_config_field_sources = {
        "review": {
            "harness": profile_source,
            "model": _phase_source(args.profile, args.review_model or args.model),
            "reasoning_effort": _phase_source(
                args.profile,
                args.review_reasoning_effort or args.reasoning_effort,
            ),
            "timeout_seconds": "cli" if args.timeout_seconds is not None else profile_source,
        },
        "triage": {
            "enabled": "cli" if args.triage_enabled is not None else profile_source,
            "harness": "cli" if args.triage_harness is not None else profile_source,
            "model": "cli" if args.triage_model is not None else profile_source,
            "reasoning_effort": "cli" if args.triage_reasoning_effort is not None else profile_source,
            "timeout_seconds": (
                "cli"
                if args.timeout_seconds is not None or args.triage_timeout_seconds is not None
                else profile_source
            ),
            "contract": "cli" if args.triage_contract is not None else profile_source,
            "routing_enabled": "cli" if args.routing_enabled is not None else profile_source,
            "allow_model_escalation": (
                "cli" if args.allow_model_escalation is not None else profile_source
            ),
        },
        "remediation": {
            "harness": profile_source,
            "model": _phase_source(args.profile, args.remediation_model or args.model),
            "reasoning_effort": _phase_source(
                args.profile,
                args.remediation_reasoning_effort or args.reasoning_effort,
            ),
            "timeout_seconds": "cli" if args.timeout_seconds is not None else profile_source,
            "sandbox": "cli" if args.exec_sandbox is not None else profile_source,
        },
        "commit_message": {
            "enabled": "cli" if args.commit_after_remediation is not None else profile_source,
            "harness": "cli" if args.commit_message_harness is not None else profile_source,
            "model": _phase_source(args.profile, args.commit_message_model or args.model),
            "reasoning_effort": "cli" if args.commit_reasoning_effort is not None else profile_source,
            "timeout_seconds": "cli" if args.timeout_seconds is not None else profile_source,
        },
        "checks": {
            "commands": "cli" if args.check is not None else profile_source,
            "timeout_seconds": "cli" if args.timeout_seconds is not None else profile_source,
        },
    }
    config = LoopConfig(
        base=pick(args.base, profile.pipeline.base, "main"),
        max_iterations=max_iterations,
        codex_bin=pick(args.codex_bin, profile.runtime.codex_bin, "codex"),
        harness_executables=harness_executables,
        cwd=cwd,
        artifact_dir=artifact_dir,
        preflight_enabled=True,
        artifact_dir_is_default=artifact_dir_value is None,
        model=args.model,
        review_harness=profile.review.harness,
        remediation_harness=profile.remediation.harness,
        triage_harness=triage_harness,
        commit_message_harness=commit_message_harness,
        review_model=review_model,
        remediation_model=remediation_model,
        reasoning_effort=args.reasoning_effort,
        review_reasoning_effort=review_reasoning_effort,
        remediation_reasoning_effort=remediation_reasoning_effort,
        commit_after_remediation=commit_after_remediation,
        commit_message_model=commit_message_model,
        commit_message_prompt=args.commit_message_prompt or profile.commit.message_prompt,
        commit_message_prompt_overridden=(
            args.commit_message_prompt is not None or profile.commit.message_prompt is not None
        ),
        commit_on_hook_failure=commit_on_hook_failure,
        commit_reasoning_effort=commit_reasoning_effort,
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
        output_last_message=pick(args.output_last_message, profile.runtime.output_last_message, True),
        dry_run=args.dry_run,
        final_review=pick(args.final_review, profile.pipeline.final_review, True),
        max_remediation_input_chars=pick(
            args.max_remediation_input_chars,
            profile.runtime.max_remediation_input_chars,
            200_000,
        ),
        terminal_excerpt_chars=pick(
            args.terminal_excerpt_chars,
            profile.runtime.terminal_excerpt_chars,
            4_000,
        ),
        timeout_seconds=timeout_seconds,
        review_timeout_seconds=review_timeout_seconds,
        remediation_timeout_seconds=remediation_timeout_seconds,
        timeout_seconds_display=timeout_seconds_display,
        review_timeout_seconds_display=review_timeout_seconds_display,
        remediation_timeout_seconds_display=remediation_timeout_seconds_display,
        triage_timeout_seconds_display=triage_timeout_seconds_display,
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
        timeout_seconds if timeout_seconds is not None else config.review_timeout_seconds
    )
    saved_remediation_timeout_seconds = (
        timeout_seconds if timeout_seconds is not None else config.remediation_timeout_seconds
    )
    saved_triage_timeout_seconds = (
        timeout_seconds
        if timeout_seconds is not None and config.triage_enabled
        else config.triage_timeout_seconds
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
            routes=(
                dict(config.profile_v2.triage.routes)
                if config.profile_v2 is not None
                else {}
            ),
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
            timeout_seconds=config.commit_timeout_seconds,
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
            terminal_excerpt_chars=config.terminal_excerpt_chars,
        ),
        budgets=profiles.BudgetConfig(
            max_wall_seconds=config.budget_config.max_wall_seconds,
            max_tokens=config.budget_config.max_tokens,
            max_usd=config.budget_config.max_usd,
            soft_warn_fraction=config.budget_config.soft_warn_fraction,
        ),
    )
