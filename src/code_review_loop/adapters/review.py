"""ReviewHarness adapter body (REVREM-TASK-003 Wave C3a step 2).

Hosts ``run_codex_review`` and its phase-specific helpers, moved verbatim from
``code_review_loop.cli``. Loop-shell helpers (``progress_event``,
``write_artifact``, etc.) live in ``adapters.phase_support`` so this module
does not import the runner or CLI edge.
"""

from __future__ import annotations

import json
import shlex
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from code_review_loop import (
    artifacts,
    harnesses,
    prompts_composer,
    provider_failures,
    provider_observations,
)
from code_review_loop.adapters import phase_support
from code_review_loop.adapters.git import (
    GitContextCache,
    cached_base_commit,
    cached_diff_base_head,
    cached_merge_base,
    run_git_preflight,
)
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
EXTERNAL_REVIEW_PROMPT_TAIL = (
    "Use the supplied diff context as the authoritative patch input. "
    "If shell or tool access is unavailable, still review the supplied diff. "
    "Do not claim that commands or tests ran unless their output is included "
    "in this prompt or you successfully ran them yourself.\n"
)
REVIEW_RETRY_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class ExternalReviewPrompt:
    prompt: str
    provider_context: str
    context_chars: int
    input_cap_chars: int
    truncated: bool


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
    external_prompt: ExternalReviewPrompt | None = None
    if ctx.git_context_cache is not None:
        ctx.git_context_cache.invalidate_head_sha(str(config.cwd))
    if config.review_harness not in {"codex", "fake"}:
        review_context = build_external_review_context(
            config, git_context_cache=ctx.git_context_cache
        )
        try:
            external_prompt = compose_external_review_prompt(config, review_context)
            phase_support.write_artifact(
                config.artifact_dir / f"{artifact_label}-context.txt",
                review_context,
            )
            if (
                external_prompt.truncated
                and config.external_review_truncation_policy == "fail"
            ):
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
                        prompt_chars=None,
                        prompt_delivery=None,
                        prompt_context_chars=external_prompt.context_chars,
                        prompt_truncated=external_prompt.truncated,
                    ),
                    ctx=ctx,
                    metadata={
                        "command": phase_support.command_for_progress(list(command)),
                        "harness": config.review_harness,
                        **external_review_prompt_metadata(external_prompt, config=config),
                    },
                )
                raise RuntimeError(
                    "prompted review context exceeds external_review_input_chars "
                    f"({external_prompt.context_chars} context chars; cap "
                    f"{external_prompt.input_cap_chars}) and "
                    "external_review_truncation_policy=fail"
                )
            review_prompt = external_prompt.prompt
            phase_support.write_artifact(
                config.artifact_dir / f"{artifact_label}-prompt.txt",
                review_prompt,
            )
            prompt_artifact_path = config.artifact_dir / f"{artifact_label}-prompt.txt"
            invocation = harnesses.prepare_prompt_invocation(
                config.review_harness,
                command,
                review_prompt,
                prompt_artifact_path=prompt_artifact_path,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        command = invocation.command
        review_prompt = invocation.stdin
    else:
        try:
            invocation = harnesses.prepare_prompt_invocation(
                config.review_harness,
                command,
                None,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
    prompt_metadata = phase_support.prompt_invocation_metadata(invocation)
    phase_support.set_phase_terminal_title(config, "review", display_label)
    phase_support.ensure_model_budget(config, phase="review", iteration=display_label, ctx=ctx)
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
            prompt_chars=prompt_metadata.get("prompt_chars"),
            prompt_delivery=prompt_metadata["prompt_delivery"],
            prompt_context_chars=(
                external_prompt.context_chars if external_prompt is not None else None
            ),
            prompt_truncated=(external_prompt.truncated if external_prompt is not None else None),
        ),
        ctx=ctx,
        metadata={
            "command": phase_support.command_for_progress(list(command)),
            "harness": config.review_harness,
            **prompt_metadata,
            **external_review_prompt_metadata(external_prompt, config=config),
        },
    )
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN\nREVIEW_STATUS: findings\n")
    else:
        artifact_path = config.artifact_dir / f"{artifact_label}.txt"
        if preflight_error := review_base_preflight_error(
            config, git_context_cache=ctx.git_context_cache
        ):
            phase_support.write_artifact(artifact_path, preflight_error)
            phase_support.progress_event(
                config, "review", display_label, "failed", "invalid base", ctx=ctx
            )
            raise RuntimeError(
                f"{config.review_harness} review failed for {artifact_label}; see {artifact_path}"
            )
        result = run_review_with_retry(
            config,
            runner,
            command,
            review_prompt,
            display_label,
            invocation.prompt_artifact,
            ctx=ctx,
        )
    combined = phase_support._combined_output(result)
    artifact_path = config.artifact_dir / f"{artifact_label}.txt"
    phase_support.write_artifact(artifact_path, combined)
    observation = _write_provider_observation(
        config,
        result,
        artifact_label=artifact_label,
        display_label=display_label,
    )
    phase_support.record_model_charge(
        config, result, phase="review", iteration=display_label, ctx=ctx
    )
    if review_failed_to_run(result, config.review_harness):
        failure = provider_failures.classify_provider_failure(result, harness=config.review_harness)
        _write_review_failure_diagnostic(
            config,
            result,
            artifact_label=artifact_label,
            display_label=display_label,
            artifact_path=artifact_path,
            command=command,
            failure=failure,
            observation=observation,
        )
        failure_detail = f": {failure.detail}" if failure else ""
        phase_support.progress_event(
            config,
            "review",
            display_label,
            "failed",
            f"exit {result.returncode}{failure_detail}",
            ctx=ctx,
        )
        raise RuntimeError(
            f"{config.review_harness} review failed for {artifact_label}"
            f"{failure_detail}; see {artifact_path}"
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
            _status_debug_detail(diagnostics),
            ctx=ctx,
        )
    if status == "findings" and phase_support.log_review_findings(
        config, display_label, combined, ctx=ctx
    ):
        return status, result
    if status == "findings":
        phase_support.log_review_summary_line(config, display_label, combined, head="review: ")
        phase_support.progress_event(config, "review", display_label, status, ctx=ctx)
    else:
        phase_support.progress_event(config, "review", display_label, status, ctx=ctx)
    return status, result


def _write_provider_observation(
    config: LoopConfig,
    result: CommandResult,
    *,
    artifact_label: str,
    display_label: str,
) -> dict[str, object] | None:
    if config.review_harness != "codex":
        return None
    observation = provider_observations.codex_observation(
        result,
        phase="review",
        iteration=display_label,
        requested={
            "model": config.review_model or config.model,
            "reasoning_effort": config.review_reasoning_effort or config.reasoning_effort,
            "sandbox": "read-only",
        },
    )
    if not _provider_observation_is_meaningful(observation, result):
        return None
    artifacts.write_json_artifact(
        config.artifact_dir,
        f"diagnostics-{artifact_label}-observation.json",
        observation,
    )
    return observation


def _provider_observation_is_meaningful(
    observation: dict[str, object],
    result: CommandResult,
) -> bool:
    return bool(
        observation.get("banner_detected")
        or observation.get("observed")
        or observation.get("warnings")
        or observation.get("raw_provider_finding_count")
        or observation.get("reported_command")
    )


def _write_review_failure_diagnostic(
    config: LoopConfig,
    result: CommandResult,
    *,
    artifact_label: str,
    display_label: str,
    artifact_path: Path,
    command: Sequence[str],
    failure: provider_failures.ProviderFailure | None,
    observation: dict[str, object] | None,
) -> None:
    payload: dict[str, object] = {
        "phase": "review",
        "iteration": display_label,
        "artifact": str(artifact_path),
        "command": list(command),
        "returncode": result.returncode,
        "timeout_seconds": phase_support.phase_timeout_seconds(
            config, config.review_timeout_seconds
        ),
        "stdout_chars": len(result.stdout or ""),
        "stderr_chars": len(result.stderr or ""),
        "combined_chars": len(phase_support._combined_output(result)),
    }
    if failure is not None:
        payload["failure"] = {
            "reason": failure.reason,
            "detail": failure.detail,
            "transient": failure.transient,
        }
    if observation is not None:
        payload["provider_observation"] = observation
    retry_command = _codex_review_retry_command(config)
    if retry_command is not None:
        payload["retry_command"] = retry_command
        payload["redirected_retry_command"] = (
            f"{shlex.join(retry_command)} > /tmp/revrem-review.txt 2>&1"
        )
    artifacts.write_json_artifact(
        config.artifact_dir,
        f"diagnostics-{artifact_label}-failure.json",
        payload,
    )


def _codex_review_retry_command(config: LoopConfig) -> list[str] | None:
    if config.review_harness != "codex":
        return None
    command = [phase_support._resolve_executable("codex", config)]
    model = config.review_model or config.model
    reasoning_effort = config.review_reasoning_effort or config.reasoning_effort
    if model:
        command.extend(["--model", model])
    command.extend(
        [
            "review",
            "-c",
            f'model_reasoning_effort="{reasoning_effort or "low"}"',
            "-c",
            'sandbox_mode="read-only"',
            "--base",
            config.base,
        ]
    )
    return command


def _status_debug_detail(diagnostics: dict[str, object]) -> str:
    explicit_required = diagnostics.get("explicit_status_required") is True
    bullet_label = "codex_bullets" if explicit_required else "findings"
    parts = [
        f"status={diagnostics['status']}",
        f"source={diagnostics['status_source']}",
    ]
    explicit_status = diagnostics.get("explicit_status")
    if explicit_required and explicit_status:
        parts.append(f"explicit={explicit_status}")
    parts.extend(
        [
            f"{bullet_label}={diagnostics['finding_line_count']}",
            f"clear_phrase={diagnostics['clear_phrase_present']}",
            f"tool_denial={diagnostics['tool_denial_present']}",
            f"stderr={diagnostics['stderr_present']}",
        ]
    )
    return " ".join(parts)


def run_review_with_retry(
    config: LoopConfig,
    runner: Runner,
    command: list[str],
    review_prompt: str | None,
    display_label: str,
    prompt_artifact: Path | None,
    *,
    ctx: RunContext,
) -> CommandResult:
    attempts = (
        config.provider_retry_attempts if config.review_harness not in {"codex", "fake"} else 1
    )
    last_result: CommandResult | None = None
    for attempt in range(1, attempts + 1):
        result = phase_support.run_with_waiting_progress(
            config,
            runner,
            command,
            config.cwd,
            review_prompt,
            phase_support.phase_timeout_seconds(config, config.review_timeout_seconds),
            phase="review",
            label=display_label,
            ctx=ctx,
            prompt_artifact=prompt_artifact,
        )
        last_result = result
        failure = provider_failures.classify_provider_failure(result, harness=config.review_harness)
        if (
            not review_failed_to_run(result, config.review_harness)
            or failure is None
            or not failure.transient
        ):
            return result
        phase_support.write_artifact(
            config.artifact_dir / f"review-{display_label}-attempt-{attempt}.txt",
            phase_support._combined_output(result),
        )
        if attempt < attempts:
            phase_support.progress_event(
                config,
                "review",
                display_label,
                "retry",
                failure.detail,
                ctx=ctx,
                metadata={"reason": failure.reason, "attempt": attempt},
            )
            time.sleep(config.provider_retry_backoff_seconds)
    assert last_result is not None
    return last_result


def external_review_prompt_metadata(
    prompt: ExternalReviewPrompt | None,
    *,
    config: LoopConfig,
) -> dict[str, object]:
    if prompt is None:
        return {}
    return {
        "review_context_chars": prompt.context_chars,
        "external_review_input_chars": prompt.input_cap_chars,
        "prompt_truncated": prompt.truncated,
        "review_context_supplied_in_full": not prompt.truncated,
        "external_review_truncation_policy": config.external_review_truncation_policy,
    }


def _leading_match_length(text: str, prefix: str) -> int:
    """Return the length of the longest prefix of ``prefix`` that matches
    the start of ``text``.

    Used to recover the head anchor after a second-pass trim that may
    have partially clipped the original head string.
    """
    max_len = min(len(text), len(prefix))
    matched = 0
    for i in range(max_len):
        if text[i] != prefix[i]:
            break
        matched = i + 1
    return matched


def _trailing_match_length(text: str, suffix: str) -> int:
    """Return the length of the longest suffix of ``suffix`` that matches
    the end of ``text``.

    Used to recover the tail anchor after a second-pass trim that may
    have partially clipped the original tail string. Scans from the
    end of both strings; on first mismatch returns the running count.
    """
    max_len = min(len(text), len(suffix))
    matched = 0
    for i in range(1, max_len + 1):
        if text[-i] != suffix[-i]:
            break
        matched = i
    return matched


def compose_external_review_prompt(
    config: LoopConfig,
    review_context: str,
) -> ExternalReviewPrompt:
    prompt_head = f"{phase_support.DEFAULT_REVIEW_PROMPT}\n\n"
    prompt_tail = f"\n\n{EXTERNAL_REVIEW_PROMPT_TAIL}"
    if config.external_review_input_chars < len(prompt_head) + len(prompt_tail):
        raise ValueError(
            f"external_review_input_chars ({config.external_review_input_chars}) is too small for mandatory prompt scaffolding ({len(prompt_head) + len(prompt_tail)} chars)."
        )
    original_prompt_chars = len(prompt_head) + len(review_context) + len(prompt_tail)
    available_context_chars = (
        config.external_review_input_chars - len(prompt_head) - len(prompt_tail)
    )
    trimmed_context = prompts_composer.trim_for_prompt(
        review_context,
        max(1, available_context_chars),
    )
    prompt = f"{prompt_head}{trimmed_context}{prompt_tail}"
    if len(prompt) > config.external_review_input_chars:
        prompt = prompts_composer.trim_for_prompt(prompt, config.external_review_input_chars)
        actual_head_len = _leading_match_length(prompt, prompt_head)
        actual_tail_len = _trailing_match_length(prompt, prompt_tail)
        if actual_head_len + actual_tail_len <= len(prompt):
            trimmed_context = prompt[actual_head_len : len(prompt) - actual_tail_len]
        else:
            trimmed_context = ""
    return ExternalReviewPrompt(
        prompt=prompt,
        provider_context=trimmed_context,
        context_chars=len(review_context),
        input_cap_chars=config.external_review_input_chars,
        truncated=len(prompt) < original_prompt_chars,
    )


def build_external_review_context(
    config: LoopConfig,
    *,
    git_context_cache: GitContextCache | None = None,
) -> str:
    """Compose the diff/head context block prepended to an external (non-Codex,
    non-fake) review prompt.

    When ``git_context_cache`` is supplied (typically via
    ``RunContext.git_context_cache``), the three commands shared with
    ``review_base_preflight_error`` and the three ``base...HEAD`` diffs are
    memoised on the cache so that a second invocation with the same
    ``(cwd, base, head)`` tuple skips those git calls. Working-tree commands
    (``status --short``, ``diff --cached``, ``diff``) are not cached because
    they depend on the in-flight working-tree state, which may have changed
    between calls.
    """
    sections = [
        "Review context supplied by RevRem.",
        f"Base branch: {config.base}",
        f"Working directory: {config.cwd}",
    ]
    if phase_support.lexical_git_repo_root(config.cwd) is None:
        sections.append("Git repository: unavailable")
        return "\n".join(sections) + "\n"

    base = cached_base_commit(git_context_cache, config.cwd, config.base)
    head_sha = _cached_head_sha(git_context_cache, config.cwd)
    head = _head_sha_result(head_sha)
    merge_base = cached_merge_base(git_context_cache, config.cwd, head_sha, config.base)
    sections.extend(
        [
            _format_git_context_result("HEAD", head),
            _format_git_context_result(f"{config.base} commit", base),
            _format_git_context_result("Merge base", merge_base),
        ]
    )
    if head_sha:
        diff_stat = cached_diff_base_head(
            git_context_cache, config.cwd, head_sha, config.base, stat=True
        )
        diff_name_status = cached_diff_base_head(
            git_context_cache, config.cwd, head_sha, config.base, name_status=True
        )
        diff_full = cached_diff_base_head(git_context_cache, config.cwd, head_sha, config.base)
    else:
        diff_stat = run_git_preflight(config.cwd, ["diff", "--stat", f"{config.base}...HEAD"])
        diff_name_status = run_git_preflight(
            config.cwd, ["diff", "--name-status", f"{config.base}...HEAD"]
        )
        diff_full = run_git_preflight(config.cwd, ["diff", f"{config.base}...HEAD"])
    sections.extend(
        [
            _format_git_context_result(
                "git status --short",
                run_git_preflight(config.cwd, ["status", "--short"]),
            ),
            _format_git_context_result(
                f"git diff --stat {config.base}...HEAD",
                diff_stat,
            ),
            _format_git_context_result(
                f"git diff --name-status {config.base}...HEAD",
                diff_name_status,
            ),
            _format_git_context_result(
                f"git diff {config.base}...HEAD",
                diff_full,
            ),
            _format_git_context_result(
                "git diff --cached",
                run_git_preflight(config.cwd, ["diff", "--cached"]),
            ),
            _format_git_context_result(
                "git diff",
                run_git_preflight(config.cwd, ["diff"]),
            ),
        ]
    )
    return "\n\n".join(sections) + "\n"


def _cached_head_sha(cache: GitContextCache | None, cwd: Path) -> str:
    """Return the cached HEAD SHA for ``cwd`` or run ``git rev-parse HEAD``.

    The result is memoised on ``GitContextCache.head_sha`` so a sequence of
    ``build_external_review_context`` calls in a single phase avoids
    re-running the subprocess. The cache is invalidated at phase
    boundaries (see ``invalidate_head_sha``) to pick up a new SHA after
    remediation commits.
    """
    key = str(cwd)
    if cache is not None:
        cached = cache.head_sha.get(key)
        if cached is not None:
            return cached
    result = run_git_preflight(cwd, ["rev-parse", "HEAD"])
    sha = result.stdout.strip()
    if cache is not None and result.returncode == 0 and sha:
        cache.head_sha[key] = sha
    return sha if result.returncode == 0 else ""


def _head_sha_result(sha: str) -> CommandResult:
    """Build a ``CommandResult`` stub that mirrors ``git rev-parse HEAD`` output.

    Lets ``build_external_review_context`` feed the cached SHA into
    ``_format_git_context_result`` without re-running the subprocess.
    """
    return CommandResult(["git", "rev-parse", "HEAD"], 0, stdout=sha + "\n")


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


def review_base_preflight_error(
    config: LoopConfig,
    *,
    git_context_cache: GitContextCache | None = None,
) -> str | None:
    if config.dry_run or phase_support.lexical_git_repo_root(config.cwd) is None:
        return None

    inside = run_git_preflight(config.cwd, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    base = config.base
    base_result = cached_base_commit(git_context_cache, config.cwd, base)
    if base_result.returncode != 0:
        return (
            f"Review base preflight failed: base {base!r} is not a local commit.\n"
            f"Command: git rev-parse --verify {base}^{{commit}}\n"
            f"{phase_support._combined_output(base_result)}"
        )

    head = _cached_head_sha(git_context_cache, config.cwd) or "HEAD"
    merge_base = cached_merge_base(git_context_cache, config.cwd, head, base)
    if merge_base.returncode == 0:
        return None

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


def review_failed_to_run(result: CommandResult, harness: str) -> bool:
    """Distinguish review invocation failures from review findings.

    The ``harness`` argument is a forward-compat hook: it is forwarded to
    ``provider_failures.classify_provider_failure`` so harness-specific
    classification rules can be added in the future without an API change.
    ``classify_provider_failure`` is currently harness-agnostic (it
    discards the value) and is the gate that turns return codes and stderr
    patterns into a structured provider-failure reason (see
    ``tests/test_provider_failures.py`` for the failure cases this guards
    against). Callers must continue to pass ``config.review_harness`` for
    that forward compatibility.
    """
    if result.returncode == 0:
        return False
    if result.returncode < 0:
        return True
    if result.returncode >= 2:
        return True
    if detect_review_status(phase_support._combined_output(result), harness=harness) in {
        "clear",
        "findings",
    }:
        return False
    if provider_failures.classify_provider_failure(result, harness=harness) is not None:
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
