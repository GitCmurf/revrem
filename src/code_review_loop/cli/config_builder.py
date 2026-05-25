"""LoopConfig assembly + small CLI-argument resolution helpers (Wave C2a).

These functions translate ``argparse.Namespace`` + profile defaults into a
``LoopConfig``. They are the front-end half of the original God-object module.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from code_review_loop import budgets, harnesses, profiles
from code_review_loop.cli.config_support import (
    git_info_exclude_path,
    lexical_git_repo_root,
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


@contextmanager
def _exclusive_lock_file(path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_dir = path.with_name(f"{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_dir}") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.rmdir(lock_dir)


def ensure_default_artifact_ignore(config: LoopConfig) -> None:
    artifact_dir = config.artifact_dir if config.artifact_dir.is_absolute() else config.cwd / config.artifact_dir
    default_runs_dir = config.cwd / ".revrem" / "runs"
    try:
        artifact_dir.relative_to(default_runs_dir)
    except ValueError:
        return
    # Keep the ignore file scoped to the workspace path the operator invoked,
    # rather than resolving through symlinked ancestry and mutating an
    # unrelated checkout's metadata.
    repo_root = lexical_git_repo_root(config.cwd)
    if repo_root == Path(tempfile.gettempdir()).resolve():
        repo_root = None
    ignore_path = git_info_exclude_path(repo_root) if repo_root is not None else None
    if ignore_path is not None and repo_root is not None:
        ignore_entry = f"{default_runs_dir.relative_to(repo_root).as_posix()}/"
    else:
        ignore_entry = "runs/"
    ignore_path = ignore_path or (config.cwd / ".revrem" / ".gitignore")
    ignore_path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock_file(ignore_path), ignore_path.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        existing = handle.read()
        existing_entries = set(existing.splitlines())
        if ignore_entry in existing_entries:
            return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        handle.seek(0)
        handle.truncate()
        handle.write(f"{existing}{ignore_entry}\n")


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


def build_loop_config(args: argparse.Namespace, cwd: Path) -> tuple[LoopConfig, str]:
    profile = profile_or_default(args.profile, cwd)
    if args.timeout_seconds is not None:
        timeout_seconds = resolve_timeout_seconds(args.timeout_seconds)
        review_timeout_seconds = timeout_seconds
        remediation_timeout_seconds = timeout_seconds
        triage_timeout_seconds = timeout_seconds if profile.triage.enabled else None
    else:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        review_timeout_seconds = resolve_profile_timeout_seconds(profile.review.timeout_seconds)
        remediation_timeout_seconds = resolve_profile_timeout_seconds(profile.remediation.timeout_seconds)
        triage_timeout_seconds = (
            resolve_profile_timeout_seconds(profile.triage.timeout_seconds)
            if profile.triage.enabled
            else None
        )
    commit_after_remediation = (
        args.commit_after_remediation
        if args.commit_after_remediation is not None
        else profile.commit.enabled
    )
    if commit_after_remediation and not args.dry_run:
        harnesses.require_implemented_harness(profile.commit.harness, field="commit.harness")
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
    commit_reasoning_effort = args.commit_reasoning_effort or remediation_reasoning_effort
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
    if args.max_iterations is not None:
        max_iterations = resolve_max_iterations(max_iterations)
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
        triage_harness=profile.triage.harness,
        commit_message_harness=profile.commit.harness,
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
        triage_enabled=profile.triage.enabled,
        triage_model=profile.triage.model,
        triage_reasoning_effort=triage_reasoning_effort,
        triage_timeout_seconds=triage_timeout_seconds,
        triage_prompt=profile.triage.prompt,
        triage_on_invalid=profile.triage.on_invalid,
        triage_contract=profile.triage.contract,
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
        profile_v2=profile,
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
