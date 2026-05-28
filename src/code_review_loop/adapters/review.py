"""ReviewHarness adapter body (REVREM-TASK-003 Wave C3a step 2).

Hosts ``run_codex_review`` and its phase-specific helpers, moved verbatim from
``code_review_loop.cli``. Loop-shell helpers (``progress_event``,
``write_artifact``, etc.) live in ``adapters.phase_support`` so this module
does not import the runner or CLI edge.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from code_review_loop import harnesses
from code_review_loop.adapters import phase_support
from code_review_loop.adapters.git import run_git_preflight
from code_review_loop.core.ports import CommandResult, ReviewOutcome, ReviewRequest, RunContext
from code_review_loop.core.review_interpretation import (
    detect_review_status,
    review_status_diagnostics,
)

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


def build_review_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.review_harness,
            role="review",
            executable=phase_support._resolve_executable(config.review_harness, config),
            base=config.base,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
        )
    )


def run_codex_review(
    config: LoopConfig,
    runner: Runner,
    artifact_label: str,
    *,
    display_label: str | None = None,
    ctx: RunContext,
) -> tuple[str, CommandResult]:
    display_label = display_label or artifact_label
    command = build_review_command(config)
    review_prompt = None
    if config.review_harness not in {"codex", "fake"}:
        review_prompt = (
            f"{phase_support.DEFAULT_REVIEW_PROMPT}\n\nBase branch: {config.base}\n"
            f"Working directory: {config.cwd}\n"
        )
        command, review_prompt = harnesses.prepare_prompt_invocation(
            config.review_harness,
            command,
            review_prompt,
        )
    phase_support.set_phase_terminal_title(config, "review", display_label)
    phase_support.ensure_model_budget(config, phase="review", iteration=display_label, ctx=ctx)
    phase_support.progress_event(config, "review", display_label, "start", shlex.join(command), ctx=ctx)
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN\nREVIEW_STATUS: findings\n")
    else:
        artifact_path = config.artifact_dir / f"{artifact_label}.txt"
        if preflight_error := review_base_preflight_error(config):
            phase_support.write_artifact(artifact_path, preflight_error)
            phase_support.progress_event(config, "review", display_label, "failed", "invalid base", ctx=ctx)
            raise RuntimeError(f"codex review failed for {artifact_label}; see {artifact_path}")
        result = runner(command, config.cwd, review_prompt, phase_support.phase_timeout_seconds(config, config.review_timeout_seconds))
    combined = phase_support._combined_output(result)
    artifact_path = config.artifact_dir / f"{artifact_label}.txt"
    phase_support.write_artifact(artifact_path, combined)
    phase_support.record_model_charge(config, result, phase="review", iteration=display_label, ctx=ctx)
    if review_failed_to_run(result):
        phase_support.progress_event(config, "review", display_label, "failed", f"exit {result.returncode}", ctx=ctx)
        raise RuntimeError(f"codex review failed for {artifact_label}; see {artifact_path}")
    status = detect_review_status(combined)
    if config.debug_status_detection:
        diagnostics = review_status_diagnostics(combined)
        phase_support.write_artifact(
            config.artifact_dir / f"{artifact_label}-status.json",
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        )
        phase_support.progress_event(
            config,
            "review",
            display_label,
            "status-debug",
            (
                f"status={diagnostics['status']} "
                f"findings={diagnostics['finding_line_count']} "
                f"clear_phrase={diagnostics['clear_phrase_present']} "
                f"stderr={diagnostics['stderr_present']}"
            ),
            ctx=ctx,
        )
    if status != "findings" or not phase_support.log_review_findings(config, display_label, combined, ctx=ctx):
        phase_support.progress_event(config, "review", display_label, status, ctx=ctx)
    return status, result


def review_base_preflight_error(config: LoopConfig) -> str | None:
    if config.dry_run or phase_support.lexical_git_repo_root(config.cwd) is None:
        return None

    inside = run_git_preflight(config.cwd, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    base = config.base
    base_result = run_git_preflight(config.cwd, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    if base_result.returncode != 0:
        return (
            f"Review base preflight failed: base {base!r} is not a local commit.\n"
            f"Command: git rev-parse --verify {base}^{{commit}}\n"
            f"{phase_support._combined_output(base_result)}"
        )

    merge_base = run_git_preflight(config.cwd, ["merge-base", "HEAD", base])
    if merge_base.returncode == 0:
        return None

    head = run_git_preflight(config.cwd, ["rev-parse", "HEAD"]).stdout.strip() or "HEAD"
    base_sha = base_result.stdout.strip() or base
    hint = review_base_hint(config, base)
    return (
        f"Review base preflight failed: HEAD and base {base!r} do not share a merge base.\n"
        f"HEAD: {head}\n"
        f"{base}: {base_sha}\n"
        f"Command: git merge-base HEAD {base}\n"
        f"{phase_support._combined_output(merge_base)}"
        f"{hint}"
    )


def review_base_hint(config: LoopConfig, base: str) -> str:
    if "/" in base:
        return "Use a base branch that shares history with HEAD, or realign the local branch.\n"
    remote_base = f"origin/{base}"
    remote_base_result = run_git_preflight(
        config.cwd,
        ["rev-parse", "--verify", f"{remote_base}^{{commit}}"],
    )
    if remote_base_result.returncode == 0:
        remote_merge_base = run_git_preflight(config.cwd, ["merge-base", "HEAD", remote_base])
        if remote_merge_base.returncode == 0:
            return (
                f"Hint: {remote_base!r} does share history with HEAD. "
                f"Retry with --base {remote_base}, or update local {base!r} to match the PR base.\n"
            )
    return "Use a base branch that shares history with HEAD, or realign the local branch.\n"


def review_failed_to_run(result: CommandResult) -> bool:
    """Distinguish review invocation failures from review findings."""
    if result.returncode == 0:
        return False
    if result.returncode < 0:
        return True
    if result.returncode >= 2:
        return True

    stderr = result.stderr.lower()
    fatal_markers = (
        "error:",
        "fatal error",
        "failed to create session",
        "thread/start failed",
        "for more information, try '--help'",
    )
    return any(marker in stderr for marker in fatal_markers)


class ReviewAdapter:
    """Implements ReviewHarness via the in-module ``run_codex_review`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        status, result = run_codex_review(
            self._config,
            ctx.runner,
            request.artifact_label,
            display_label=request.display_label,
            ctx=ctx,
        )
        return ReviewOutcome(status=cast(Literal["clear", "findings", "unknown"], status), result=result)
