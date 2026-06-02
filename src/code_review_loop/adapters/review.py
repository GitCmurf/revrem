"""ReviewHarness adapter body (REVREM-TASK-003 Wave C3a step 2).

Hosts ``run_codex_review`` and its phase-specific helpers, moved verbatim from
``code_review_loop.cli``. Loop-shell helpers (``progress_event``,
``write_artifact``, etc.) live in ``adapters.phase_support`` so this module
does not import the runner or CLI edge.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from code_review_loop import harnesses
from code_review_loop.adapters import phase_support
from code_review_loop.adapters.git import run_git_preflight
from code_review_loop.core.ports import (
    CommandResult,
    ReviewOutcome,
    ReviewRequest,
    RunContext,
)
from code_review_loop.core.review_interpretation import (
    detect_review_status,
    review_status_diagnostics,
)

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]
MAX_EXTERNAL_REVIEW_DIFF_CHARS = 120_000


def build_review_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.review_harness,
            role="review",
            executable=phase_support._resolve_executable(config.review_harness, config),
            base=config.base,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
            sandbox="read-only",
            full_auto=False,
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
        review_context = build_external_review_context(config)
        review_prompt = (
            f"{phase_support.DEFAULT_REVIEW_PROMPT}\n\n{review_context}\n\n"
            "Use the supplied diff context as the authoritative patch input. "
            "If shell or tool access is unavailable, still review the supplied diff. "
            "Do not claim that commands or tests ran unless their output is included "
            "in this prompt or you successfully ran them yourself.\n"
        )
        phase_support.write_artifact(
            config.artifact_dir / f"{artifact_label}-context.txt",
            review_context,
        )
        phase_support.write_artifact(
            config.artifact_dir / f"{artifact_label}-prompt.txt",
            review_prompt,
        )
        command, review_prompt = harnesses.prepare_prompt_invocation(
            config.review_harness,
            command,
            review_prompt,
        )
    phase_support.set_phase_terminal_title(config, "review", display_label)
    phase_support.ensure_model_budget(
        config, phase="review", iteration=display_label, ctx=ctx
    )
    phase_support.progress_event(
        config,
        "review",
        display_label,
        "start",
        phase_support.resolved_phase_detail(
            command,
            harness=config.review_harness,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
            timeout_seconds=config.review_timeout_seconds_display,
            sandbox="read-only",
            source=config.phase_config_sources.get("review", "direct-config"),
        ),
        ctx=ctx,
    )
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN\nREVIEW_STATUS: findings\n")
    else:
        artifact_path = config.artifact_dir / f"{artifact_label}.txt"
        if preflight_error := review_base_preflight_error(config):
            phase_support.write_artifact(artifact_path, preflight_error)
            phase_support.progress_event(
                config, "review", display_label, "failed", "invalid base", ctx=ctx
            )
            raise RuntimeError(
                f"codex review failed for {artifact_label}; see {artifact_path}"
            )
        result = runner(
            command,
            config.cwd,
            review_prompt,
            phase_support.phase_timeout_seconds(config, config.review_timeout_seconds),
        )
    combined = phase_support._combined_output(result)
    artifact_path = config.artifact_dir / f"{artifact_label}.txt"
    phase_support.write_artifact(artifact_path, combined)
    phase_support.record_model_charge(
        config, result, phase="review", iteration=display_label, ctx=ctx
    )
    if review_failed_to_run(result):
        phase_support.progress_event(
            config,
            "review",
            display_label,
            "failed",
            f"exit {result.returncode}",
            ctx=ctx,
        )
        raise RuntimeError(
            f"codex review failed for {artifact_label}; see {artifact_path}"
        )
    status = detect_review_status(combined, harness=config.review_harness)
    if config.debug_status_detection:
        diagnostics = review_status_diagnostics(combined, harness=config.review_harness)
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
                f"source={diagnostics['status_source']} "
                f"findings={diagnostics['finding_line_count']} "
                f"clear_phrase={diagnostics['clear_phrase_present']} "
                f"tool_denial={diagnostics['tool_denial_present']} "
                f"stderr={diagnostics['stderr_present']}"
            ),
            ctx=ctx,
        )
    if status != "findings" or not phase_support.log_review_findings(
        config, display_label, combined, ctx=ctx
    ):
        phase_support.progress_event(config, "review", display_label, status, ctx=ctx)
    return status, result


def build_external_review_context(config: LoopConfig) -> str:
    sections = [
        "Review context supplied by RevRem.",
        f"Base branch: {config.base}",
        f"Working directory: {config.cwd}",
    ]
    if phase_support.lexical_git_repo_root(config.cwd) is None:
        sections.append("Git repository: unavailable")
        return "\n".join(sections) + "\n"

    head = run_git_preflight(config.cwd, ["rev-parse", "HEAD"])
    base = run_git_preflight(
        config.cwd, ["rev-parse", "--verify", f"{config.base}^{{commit}}"]
    )
    merge_base = run_git_preflight(config.cwd, ["merge-base", "HEAD", config.base])
    sections.extend(
        [
            _format_git_context_result("HEAD", head),
            _format_git_context_result(f"{config.base} commit", base),
            _format_git_context_result("Merge base", merge_base),
        ]
    )
    sections.extend(
        [
            _format_git_context_result(
                "git status --short",
                run_git_preflight(config.cwd, ["status", "--short"]),
            ),
            _format_git_context_result(
                f"git diff --stat {config.base}...HEAD",
                run_git_preflight(
                    config.cwd, ["diff", "--stat", f"{config.base}...HEAD"]
                ),
            ),
            _format_git_context_result(
                f"git diff --name-status {config.base}...HEAD",
                run_git_preflight(
                    config.cwd, ["diff", "--name-status", f"{config.base}...HEAD"]
                ),
            ),
            _format_git_context_result(
                f"git diff {config.base}...HEAD",
                run_git_preflight(config.cwd, ["diff", f"{config.base}...HEAD"]),
                max_chars=MAX_EXTERNAL_REVIEW_DIFF_CHARS,
            ),
            _format_git_context_result(
                "git diff --cached",
                run_git_preflight(config.cwd, ["diff", "--cached"]),
                max_chars=MAX_EXTERNAL_REVIEW_DIFF_CHARS,
            ),
            _format_git_context_result(
                "git diff",
                run_git_preflight(config.cwd, ["diff"]),
                max_chars=MAX_EXTERNAL_REVIEW_DIFF_CHARS,
            ),
        ]
    )
    return "\n\n".join(sections) + "\n"


def _format_git_context_result(
    label: str,
    result: CommandResult,
    *,
    max_chars: int | None = None,
) -> str:
    output = phase_support._combined_output(result).strip()
    if max_chars is not None and len(output) > max_chars:
        output = output[:max_chars] + "\n[RevRem: diff context truncated]\n"
    if not output:
        output = "[no output]"
    return f"## {label}\nExit status: {result.returncode}\n{output}"


def review_base_preflight_error(config: LoopConfig) -> str | None:
    if config.dry_run or phase_support.lexical_git_repo_root(config.cwd) is None:
        return None

    inside = run_git_preflight(config.cwd, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    base = config.base
    base_result = run_git_preflight(
        config.cwd, ["rev-parse", "--verify", f"{base}^{{commit}}"]
    )
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
        remote_merge_base = run_git_preflight(
            config.cwd, ["merge-base", "HEAD", remote_base]
        )
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
        return ReviewOutcome(
            status=cast(Literal["clear", "findings", "unknown"], status), result=result
        )
