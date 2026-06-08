"""CommitHarness adapter body (REVREM-TASK-003 Wave C3a step 5).

Hosts the commit-phase implementation: ``run_commit`` and the git/commit
helpers it composes (``git_add_command_for_commit``,
``git_worktree_status_command_for_commit``, ``git_repo_root``,
``commit_artifact_relative_path``, ``git_reset_artifact_command_for_commit``,
``commit_command_for_message``, ``classify_commit_failure``,
``commit_message_for_staged_changes``, ``deterministic_commit_message``,
``format_commit_hook_failure_for_remediation``). Shared support lives in
``adapters.phase_support`` so the adapter layer does not import the runner or
CLI edge.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from code_review_loop import artifacts, harnesses, prompts_composer
from code_review_loop.adapters import phase_support
from code_review_loop.core.ports import (
    CommandResult,
    CommitOutcome,
    CommitRequest,
    RunContext,
)
from code_review_loop.core.review_interpretation import actionable_review_output
from code_review_loop.git_status import non_artifact_status_lines
from code_review_loop.repo_roots import lexical_git_repo_root

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]

COMMIT_MESSAGE_SIDE_EFFECT_WARNING = (
    "commit-message harness mutated repository state; this model/harness is "
    "unsuitable for commit-message drafting until fixed"
)


@dataclass(frozen=True)
class _AdoptedCommit:
    head_before: str
    head_after: str
    artifact: str


def git_add_command_for_commit(_config: LoopConfig) -> list[str]:
    return ["git", "add", "-A"]


def git_worktree_status_command_for_commit(_config: LoopConfig) -> list[str]:
    return ["git", "status", "--porcelain=v1", "--untracked-files=all"]


def git_repo_root(config: LoopConfig, runner: Runner) -> Path | None:
    result = runner(
        ["git", "-C", str(config.cwd), "rev-parse", "--show-toplevel"],
        config.cwd,
        None,
        phase_support.phase_timeout_seconds(config, config.timeout_seconds),
    )
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def commit_artifact_relative_path(config: LoopConfig, repo_root: Path) -> Path | None:
    artifact_root = (
        config.artifact_dir
        if config.artifact_dir.is_absolute()
        else config.cwd / config.artifact_dir
    )
    resolved_root = artifact_root.resolve()
    try:
        artifact_rel = resolved_root.relative_to(repo_root)
    except ValueError:
        return None
    if artifact_rel == Path("."):
        raise RuntimeError(
            "refusing to auto-commit when --artifact-dir resolves to the repository root; "
            "choose a subdirectory for generated artifacts."
        )
    return artifact_rel


def reject_artifact_dir_at_repo_root(config: LoopConfig, repo_root: Path) -> None:
    commit_artifact_relative_path(config, repo_root)


def git_reset_artifact_command_for_commit(
    config: LoopConfig, repo_root: Path | None
) -> list[str] | None:
    if repo_root is None:
        return None
    artifact_rel = commit_artifact_relative_path(config, repo_root)
    if artifact_rel is None:
        return None
    # Keep generated loop artifacts out of the staged commit. Resolve artifact
    # paths from the git root so subdirectory invocations can still reset files
    # that live elsewhere inside the same repository.
    return ["git", "-C", str(repo_root), "reset", "--", artifact_rel.as_posix()]


def commit_command_for_message(
    message: str, *, allow_no_verify: bool = False
) -> list[str]:
    command = ["git", "commit"]
    if allow_no_verify:
        command.append("--no-verify")
    command.extend(["-m", message])
    return command


def classify_commit_failure(result: CommandResult) -> str:
    output = phase_support._combined_output(result)
    return (
        "hook_failed"
        if phase_support.COMMIT_HOOK_FAILURE_RE.search(output)
        else "commit_failed"
    )


def run_commit(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    *,
    ctx: RunContext,
    retrying: bool = False,
) -> str:
    phase_support.progress_event(
        config,
        "commit",
        str(iteration),
        "start",
        (
            "stage and commit verified remediation "
            f"[message_harness={config.commit_message_harness} "
            f"model={config.commit_message_model} "
            f"effort={config.commit_reasoning_effort} "
            f"timeout={_display_timeout(config.commit_timeout_seconds_display)}]"
        ),
        ctx=ctx,
    )
    if config.dry_run:
        phase_support.write_artifact(
            config.artifact_dir / f"commit-{iteration}.txt", "DRY_RUN commit skipped\n"
        )
        phase_support.progress_event(
            config, "commit", str(iteration), "skipped", "dry-run", ctx=ctx
        )
        return "skipped"

    repo_root = git_repo_root(config, runner)
    if repo_root is not None:
        reject_artifact_dir_at_repo_root(config, repo_root)
    add_result = runner(
        git_add_command_for_commit(config),
        config.cwd,
        None,
        phase_support.phase_timeout_seconds(config, config.timeout_seconds),
    )
    phase_support.write_artifact(
        config.artifact_dir / f"commit-{iteration}-add.txt",
        phase_support._combined_output(add_result),
    )
    if add_result.returncode != 0:
        phase_support.progress_event(
            config, "commit", str(iteration), "failed", "git add failed", ctx=ctx
        )
        raise RuntimeError(
            f"git add failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'commit-{iteration}-add.txt'}"
        )

    reset_command = git_reset_artifact_command_for_commit(config, repo_root)
    if reset_command is not None:
        reset_result = runner(
            reset_command,
            config.cwd,
            None,
            phase_support.phase_timeout_seconds(config, config.timeout_seconds),
        )
        phase_support.write_artifact(
            config.artifact_dir / f"commit-{iteration}-reset-artifacts.txt",
            phase_support._combined_output(reset_result),
        )
        if reset_result.returncode != 0:
            phase_support.progress_event(
                config,
                "commit",
                str(iteration),
                "failed",
                "git reset artifacts failed",
                ctx=ctx,
            )
            raise RuntimeError(
                f"git reset artifacts failed for iteration {iteration}; "
                f"see {config.artifact_dir / f'commit-{iteration}-reset-artifacts.txt'}"
            )

    diff_quiet = runner(
        ["git", "diff", "--cached", "--quiet"],
        config.cwd,
        None,
        phase_support.phase_timeout_seconds(config, config.timeout_seconds),
    )
    if diff_quiet.returncode == 0:
        phase_support.write_artifact(
            config.artifact_dir / f"commit-{iteration}.txt",
            "No staged changes to commit.\n",
        )
        phase_support.progress_event(
            config, "commit", str(iteration), "skipped", "no staged changes", ctx=ctx
        )
        return "skipped_no_changes"
    if diff_quiet.returncode != 1:
        phase_support.write_artifact(
            config.artifact_dir / f"commit-{iteration}.txt",
            phase_support._combined_output(diff_quiet),
        )
        phase_support.progress_event(
            config,
            "commit",
            str(iteration),
            "failed",
            "git diff --cached --quiet failed",
            ctx=ctx,
        )
        raise RuntimeError(f"git staged-diff check failed for iteration {iteration}")

    message = commit_message_for_staged_changes(config, runner, iteration, ctx=ctx)
    if isinstance(message, _AdoptedCommit):
        phase_support.write_artifact(
            config.artifact_dir / f"commit-{iteration}.txt",
            (
                "Commit-message harness already committed the staged changes.\n"
                f"{COMMIT_MESSAGE_SIDE_EFFECT_WARNING}.\n"
                f"HEAD before: {message.head_before}\n"
                f"HEAD after: {message.head_after}\n"
                f"Diagnostic: {message.artifact}\n"
            ),
        )
        phase_support.progress_event(
            config,
            "commit",
            str(iteration),
            "committed",
            f"adopted commit-message side-effect commit; {COMMIT_MESSAGE_SIDE_EFFECT_WARNING}",
            ctx=ctx,
        )
        return "committed"
    commit_result = runner(
        commit_command_for_message(
            message,
            allow_no_verify=retrying and config.commit_on_hook_failure == "no-verify",
        ),
        config.cwd,
        None,
        phase_support.phase_timeout_seconds(config, config.timeout_seconds),
    )
    commit_artifact_path = config.artifact_dir / f"commit-{iteration}.txt"
    commit_output = phase_support._combined_output(commit_result)
    phase_support.write_artifact(commit_artifact_path, commit_output)
    if commit_result.returncode != 0:
        kind = classify_commit_failure(commit_result)
        detail = (
            "git commit hook failed" if kind == "hook_failed" else "git commit failed"
        )
        phase_support.progress_event(
            config, "commit", str(iteration), "failed", detail, ctx=ctx
        )
        raise phase_support.CommitFailed(
            iteration=iteration,
            kind=kind,
            artifact_path=commit_artifact_path,
            output=commit_output,
        )
    phase_support.write_artifact(
        config.artifact_dir / f"commit-{iteration}-message.txt", message + "\n"
    )
    phase_support.progress_event(
        config, "commit", str(iteration), "committed", message, ctx=ctx
    )
    return "committed"


def commit_message_for_staged_changes(
    config: LoopConfig, runner: Runner, iteration: int, ctx: RunContext
) -> str | _AdoptedCommit:
    timeout_seconds = phase_support.phase_timeout_seconds(
        config, config.commit_timeout_seconds
    )
    stat = runner(
        ["git", "diff", "--cached", "--stat"], config.cwd, None, timeout_seconds
    )
    names = runner(
        ["git", "diff", "--cached", "--name-only"], config.cwd, None, timeout_seconds
    )
    stat_stdout = stat.stdout or ""
    names_stdout = names.stdout or ""
    staged_paths = [line.strip() for line in names_stdout.splitlines() if line.strip()]
    fallback_context = commit_message_fallback_context(config, iteration)
    fallback = deterministic_commit_message(
        staged_paths=staged_paths,
        context=fallback_context,
    )
    context = "\n".join(
        part
        for part in (
            "Files:",
            names_stdout.strip(),
            "",
            "Stat:",
            stat_stdout.strip(),
            "",
            "Review/remediation context:",
            fallback_context.strip(),
        )
        if part is not None and part != ""
    )
    if not config.commit_message_model:
        return fallback
    before_head = _commit_message_head(config, runner, timeout_seconds=timeout_seconds)
    before_cached_raw = _commit_message_cached_raw(
        config, runner, timeout_seconds=timeout_seconds
    )
    command = phase_support.build_commit_message_command(config)
    prompt_root = (
        config.commit_message_prompt or phase_support.DEFAULT_COMMIT_MESSAGE_PROMPT
    )
    prompt_root = (
        f"{prompt_root.rstrip()}\n"
        "Do not edit, write, stage, or commit files. Do not run git add or "
        "git commit. Print only the subject; repository mutations are detected "
        "and recorded as commit-message side effects.\n"
    )
    prompt = f"{prompt_root}\n{prompts_composer.trim_for_prompt(context, config.max_remediation_input_chars)}"
    prompt_artifact_path = (
        config.artifact_dir / f"commit-{iteration}-message-prompt.txt"
    )
    phase_support.write_artifact(prompt_artifact_path, prompt)
    invocation = harnesses.prepare_prompt_invocation(
        config.commit_message_harness,
        command,
        prompt,
        prompt_artifact_path=prompt_artifact_path,
    )
    command = invocation.command
    prompt_input = invocation.stdin
    prompt_metadata = phase_support.prompt_invocation_metadata(invocation)
    phase_support.ensure_model_budget(
        config, phase="commit-message", iteration=iteration, ctx=ctx
    )
    if config.commit_reasoning_effort_adjustment:
        phase_support.progress_event(
            config,
            "commit-message",
            str(iteration),
            "config-adjusted",
            (
                "reasoning_effort "
                f"{config.commit_reasoning_effort_requested}->{config.commit_reasoning_effort} "
                f"({config.commit_reasoning_effort_adjustment})"
            ),
            ctx=ctx,
        )
    phase_support.progress_event(
        config,
        "commit-message",
        str(iteration),
        "start",
        phase_support.resolved_phase_detail(
            command,
            harness=config.commit_message_harness,
            model=config.commit_message_model,
            reasoning_effort=config.commit_reasoning_effort,
            timeout_seconds=config.commit_timeout_seconds_display,
            sandbox="read-only",
            source=config.phase_config_sources.get("commit_message", "direct-config"),
            prompt_chars=prompt_metadata.get("prompt_chars"),
            prompt_delivery=prompt_metadata["prompt_delivery"],
        ),
        ctx=ctx,
        metadata={
            "command": phase_support.command_for_progress(list(command)),
            "harness": config.commit_message_harness,
            **prompt_metadata,
        },
    )
    before_status = _commit_message_worktree_status(
        config,
        runner,
        timeout_seconds=timeout_seconds,
    )
    result = phase_support.run_with_waiting_progress(
        config,
        runner,
        command,
        config.cwd,
        prompt_input,
        timeout_seconds,
        phase="commit-message",
        label=str(iteration),
        ctx=ctx,
        prompt_artifact=invocation.prompt_artifact,
    )
    phase_support.write_artifact(
        config.artifact_dir / f"commit-{iteration}-message-draft.txt",
        phase_support._combined_output(result),
    )
    phase_support.record_model_charge(
        config, result, phase="commit-message", iteration=iteration, ctx=ctx
    )
    side_effect_status = _handle_commit_message_side_effects(
        config,
        runner,
        iteration,
        before_status=before_status,
        timeout_seconds=timeout_seconds,
    )
    repo_mutation = _handle_commit_message_repo_mutation(
        config,
        runner,
        iteration,
        before_head=before_head,
        before_cached_raw=before_cached_raw,
        timeout_seconds=timeout_seconds,
    )
    if repo_mutation is not None:
        return repo_mutation
    if side_effect_status == "fallback":
        artifacts.write_json_artifact(
            config.artifact_dir,
            f"commit-{iteration}-message-fallback.json",
            {
                "iteration": iteration,
                "reason": "model_drafting_side_effects",
                "subject": fallback,
                "draft_artifact": f"commit-{iteration}-message-draft.txt",
            },
        )
        phase_support.progress_event(
            config,
            "commit-message",
            str(iteration),
            "fallback",
            f"model drafting wrote files; using deterministic subject: {fallback}",
            ctx=ctx,
        )
        return fallback
    if result.returncode != 0:
        artifacts.write_json_artifact(
            config.artifact_dir,
            f"commit-{iteration}-message-fallback.json",
            {
                "iteration": iteration,
                "reason": "model_drafting_failed",
                "subject": fallback,
                "draft_artifact": f"commit-{iteration}-message-draft.txt",
            },
        )
        phase_support.progress_event(
            config,
            "commit-message",
            str(iteration),
            "fallback",
            f"model drafting failed; using deterministic subject: {fallback}",
            ctx=ctx,
        )
        return fallback
    subject = model_commit_message_subject(
        phase_support._combined_output(result),
        enforce_revrem_conventional=not config.commit_message_prompt_overridden,
    )
    if subject is not None:
        return subject
    artifacts.write_json_artifact(
        config.artifact_dir,
        f"commit-{iteration}-message-fallback.json",
        {
            "iteration": iteration,
            "reason": "model_drafting_invalid",
            "subject": fallback,
            "draft_artifact": f"commit-{iteration}-message-draft.txt",
        },
    )
    phase_support.progress_event(
        config,
        "commit-message",
        str(iteration),
        "fallback",
        f"model drafting invalid; using deterministic subject: {fallback}",
        ctx=ctx,
    )
    return fallback


def _commit_message_worktree_status(
    config: LoopConfig,
    runner: Runner,
    *,
    timeout_seconds: float | None = None,
) -> set[str] | None:
    if lexical_git_repo_root(config.cwd) is None:
        return None
    result = runner(
        git_worktree_status_command_for_commit(config),
        config.cwd,
        None,
        timeout_seconds,
    )
    if result.returncode != 0:
        return None
    return set(non_artifact_status_lines(config, result.stdout))


def _commit_message_head(
    config: LoopConfig,
    runner: Runner,
    *,
    timeout_seconds: float | None,
) -> str | None:
    if lexical_git_repo_root(config.cwd) is None:
        return None
    result = runner(["git", "rev-parse", "HEAD"], config.cwd, None, timeout_seconds)
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def _commit_message_cached_raw(
    config: LoopConfig,
    runner: Runner,
    *,
    timeout_seconds: float | None,
) -> str | None:
    if lexical_git_repo_root(config.cwd) is None:
        return None
    result = runner(["git", "diff", "--cached", "--raw"], config.cwd, None, timeout_seconds)
    if result.returncode != 0:
        return None
    return result.stdout


def _commit_message_cached_is_empty(
    config: LoopConfig,
    runner: Runner,
    *,
    timeout_seconds: float | None,
) -> bool:
    result = runner(
        ["git", "diff", "--cached", "--quiet"],
        config.cwd,
        None,
        timeout_seconds,
    )
    return result.returncode == 0


def _handle_commit_message_repo_mutation(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    *,
    before_head: str | None,
    before_cached_raw: str | None,
    timeout_seconds: float | None,
) -> _AdoptedCommit | None:
    if before_head is None and before_cached_raw is None:
        return None
    after_head = _commit_message_head(config, runner, timeout_seconds=timeout_seconds)
    after_cached_raw = _commit_message_cached_raw(
        config, runner, timeout_seconds=timeout_seconds
    )
    head_changed = bool(before_head and after_head and before_head != after_head)
    cached_changed = (
        before_cached_raw is not None
        and after_cached_raw is not None
        and before_cached_raw != after_cached_raw
    )
    if not head_changed and not cached_changed:
        return None
    clean_status = _commit_message_worktree_status(
        config, runner, timeout_seconds=timeout_seconds
    )
    cached_empty = _commit_message_cached_is_empty(
        config, runner, timeout_seconds=timeout_seconds
    )
    artifact = _write_commit_message_side_effect_artifact(
        config.artifact_dir,
        iteration,
        kind=(
            "self_commit_adopted"
            if head_changed and clean_status == set() and cached_empty
            else "unsafe_repo_mutation"
        ),
        severity=(
            "warning"
            if head_changed and clean_status == set() and cached_empty
            else "error"
        ),
        head_before=before_head,
        head_after=after_head,
        cached_diff_changed=cached_changed,
        cached_diff_empty=cached_empty,
        non_artifact_status_lines=sorted(clean_status or []),
        warning=COMMIT_MESSAGE_SIDE_EFFECT_WARNING,
    )
    if head_changed and clean_status == set() and cached_empty and after_head:
        return _AdoptedCommit(
            head_before=before_head or "",
            head_after=after_head,
            artifact=str(artifact),
        )
    raise RuntimeError(
        "commit-message drafting mutated repository HEAD or staged changes; "
        f"see {artifact}"
    )


def _handle_commit_message_side_effects(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    *,
    before_status: set[str] | None,
    timeout_seconds: float | None,
) -> Literal["clean", "fallback"]:
    if before_status is None:
        return "clean"
    after_status = _commit_message_worktree_status(
        config,
        runner,
        timeout_seconds=timeout_seconds,
    )
    if after_status is None:
        return "clean"
    new_lines = sorted(after_status - before_status)
    if not new_lines:
        return "clean"
    # ``git status --porcelain`` reports paths relative to the repository root
    # even when RevRem is launched from a subdirectory, so resolve any new
    # ``??`` paths from the lexical git root (falling back to ``config.cwd``
    # outside a worktree) before deciding whether the path is safe to remove.
    # Otherwise a root-level helper file created by the model is treated as
    # missing/unsafe and the commit phase aborts instead of falling back.
    status_root = lexical_git_repo_root(config.cwd) or config.cwd.resolve()
    created_paths: list[str] = []
    unsafe_lines: list[str] = []
    for line in new_lines:
        if not line.startswith("?? "):
            unsafe_lines.append(line)
            continue
        path_text = line[3:].strip()
        if not path_text:
            unsafe_lines.append(line)
            continue
        target = (status_root / path_text).resolve()
        try:
            target.relative_to(status_root)
        except ValueError:
            unsafe_lines.append(line)
            continue
        if not target.exists() or target.is_dir():
            unsafe_lines.append(line)
            continue
        try:
            target.unlink()
            created_paths.append(path_text)
        except OSError:
            unsafe_lines.append(line)
    kind = "helper_files_removed" if created_paths else "unsafe_worktree_paths"
    _write_commit_message_side_effect_artifact(
        config.artifact_dir,
        iteration,
        kind=kind,
        severity="warning" if created_paths and not unsafe_lines else "error",
        created_paths_removed=created_paths,
        unsafe_status_lines=unsafe_lines,
        warning=COMMIT_MESSAGE_SIDE_EFFECT_WARNING,
    )
    if unsafe_lines:
        raise RuntimeError(
            "commit-message drafting modified existing or unsafe worktree paths; "
            f"see {config.artifact_dir / f'commit-{iteration}-message-side-effects.json'}"
        )
    return "fallback" if created_paths else "clean"


def _write_commit_message_side_effect_artifact(
    artifact_dir: Path,
    iteration: int,
    *,
    kind: str,
    severity: str,
    warning: str,
    created_paths_removed: list[str] | None = None,
    unsafe_status_lines: list[str] | None = None,
    head_before: str | None = None,
    head_after: str | None = None,
    cached_diff_changed: bool | None = None,
    cached_diff_empty: bool | None = None,
    non_artifact_status_lines: list[str] | None = None,
) -> Path:
    return artifacts.write_json_artifact(
        artifact_dir,
        f"commit-{iteration}-message-side-effects.json",
        {
            "schema_version": "1.0",
            "iteration": iteration,
            "kind": kind,
            "severity": severity,
            "warning": warning,
            "created_paths_removed": created_paths_removed or [],
            "unsafe_status_lines": unsafe_status_lines or [],
            "head_before": head_before,
            "head_after": head_after,
            "cached_diff_changed": cached_diff_changed,
            "cached_diff_empty": cached_diff_empty,
            "non_artifact_status_lines": non_artifact_status_lines or [],
        },
    )


def model_commit_message_subject(
    draft_output: str,
    *,
    enforce_revrem_conventional: bool,
) -> str | None:
    return phase_support.extract_commit_message_subject(
        actionable_review_output(draft_output),
        enforce_revrem_conventional=enforce_revrem_conventional,
    )


def commit_message_fallback_context(config: LoopConfig, iteration: int) -> str:
    parts: list[str] = []
    for name in (
        f"review-{iteration}.txt",
        f"remediation-{iteration}.txt",
        f"remediation-{iteration}-last-message.txt",
    ):
        path = config.artifact_dir / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            parts.append(text)
    return prompts_composer.trim_for_prompt("\n\n".join(parts), 20_000)


def deterministic_commit_message(
    *,
    staged_paths: list[str] | None = None,
    context: str = "",
) -> str:
    paths = staged_paths or []
    change_type = _commit_type(paths, context=context)
    scope = _commit_scope(paths, change_type=change_type)
    summary = _commit_summary(change_type, paths, context=context)
    summary = _cap_commit_summary(change_type, scope, summary)
    if scope:
        return f"{change_type}({scope}): {summary} (RevRem)"
    return f"{change_type}: {summary} (RevRem)"


def _cap_commit_summary(change_type: str, scope: str, summary: str) -> str:
    prefix = f"{change_type}({scope}): " if scope else f"{change_type}: "
    suffix = " (RevRem)"
    available = 72 - len(prefix) - len(suffix)
    if available < 1:
        return "local changes"
    if len(summary) <= available:
        return summary
    trimmed = summary[:available].rsplit(" ", 1)[0].strip(" .,:;-")
    return trimmed or "local changes"


def _commit_scope(paths: list[str], *, change_type: str) -> str:
    if not paths:
        return "review"
    path_parts = [Path(path).parts for path in paths if Path(path).parts]
    if not path_parts:
        return "review"
    first_parts = [parts[0] for parts in path_parts]
    counts: dict[str, int] = {}
    for part in first_parts:
        counts[part] = counts.get(part, 0) + 1
    dominant = max(counts, key=lambda part: (counts[part], part))
    if dominant == "src":
        scope = _src_scope(paths)
    elif all(len(parts) == 1 for parts in path_parts if parts[0] == dominant):
        scope = ""
    else:
        scope = _slug(dominant)
    return "" if _is_low_signal_scope(scope, change_type=change_type) else scope


def _src_scope(paths: list[str]) -> str:
    candidates: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.parts or path.parts[0] != "src":
            continue
        if len(path.parts) >= 4 and path.parts[1] == "code_review_loop":
            candidates.append(path.parts[2])
        elif len(path.parts) == 2 or (
            len(path.parts) == 3 and path.parts[1] == "code_review_loop"
        ):
            candidates.append(path.stem)
        elif len(path.parts) > 2:
            candidates.append(path.parts[1])
    if not candidates:
        return "src"
    counts: dict[str, int] = {}
    for part in candidates:
        counts[part] = counts.get(part, 0) + 1
    return _slug(max(counts, key=lambda part: (counts[part], part)))


def _commit_type(paths: list[str], *, context: str = "") -> str:
    if paths and all(
        path.startswith("docs/") or path.endswith(".md") for path in paths
    ):
        return "docs"
    if paths and all(path.startswith("tests/") for path in paths):
        return "test"
    leading_context = _commit_context_leading_text(context).lower()
    if _contains_any(
        leading_context,
        (
            r"\bfix(?:es|ed)?\b",
            r"\bbug(?:s)?\b",
            r"\bregression(?:s)?\b",
            r"\bpreserve(?:s|d)?\b",
            r"\bavoid(?:s|ed)?\b",
            r"\bprevent(?:s|ed)?\b",
            r"\brestore(?:s|d)?\b",
            r"\bbroken\b",
            r"\btest failure(?:s)?\b",
            r"\bfailing test(?:s)?\b",
        ),
    ):
        return "fix"
    if _contains_any(
        leading_context,
        (
            r"\bperformance\b",
            r"\bcach(?:e|ing)\b",
            r"\bfaster\b",
            r"\bspeed\b",
            r"\blatency\b",
        ),
    ):
        return "perf"
    if _contains_any(
        leading_context,
        (
            r"\brefactor(?:s|ed)?\b",
            r"\bextract(?:s|ed)?\b",
            r"\bsplit(?:s)?\b",
            r"\brestructure(?:s|d)?\b",
            r"\bdecompose(?:s|d)?\b",
        ),
    ):
        return "refactor"
    if _contains_any(
        leading_context,
        (
            r"\badd(?:s|ed)?\b",
            r"\benable(?:s|d)?\b",
            r"\bsupport(?:s|ed)?\b",
            r"\bnew\b",
            r"\bfeature(?:s)?\b",
        ),
    ):
        return "feat"
    return "chore"


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _commit_summary(change_type: str, paths: list[str], *, context: str) -> str:
    leading_context = _commit_context_leading_text(context)
    context_summary = _summary_from_context(change_type, leading_context)
    if context_summary:
        return context_summary
    return _summary_from_paths(change_type, paths)


def _commit_context_leading_text(context: str) -> str:
    for raw_line in context.splitlines():
        line = _clean_context_line(raw_line)
        if line:
            return line
    return ""


def _clean_context_line(line: str) -> str:
    text = line.strip().strip("-* ")
    text = re.sub(r"^\[[A-Z]\d+\]\s*", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\s+[-—]\s+/.+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .:")


def _summary_from_context(change_type: str, text: str) -> str:
    if not text:
        return ""
    lower = text.lower()
    verb = _summary_verb(change_type)
    return _noun_from_text(lower, verb=verb)


def _noun_from_text(lower_text: str, *, verb: str) -> str:
    words = re.findall(r"[a-z][a-z0-9-]+", lower_text)
    stop_words = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
        "with",
        "from",
        "this",
        "that",
        "when",
        "where",
        "into",
        "while",
        "without",
        "by",
        "can",
        "could",
        "should",
        "would",
        "must",
        "may",
        "might",
        "please",
        "review",
        "remediation",
        "revrem",
        "codex",
        "issue",
        "finding",
        "findings",
    }
    trigger_words = _all_summary_trigger_words()
    useful: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word == verb or word in stop_words or word in trigger_words:
            continue
        if word in seen:
            continue
        seen.add(word)
        useful.append(word)
    return " ".join(useful[:4]) if useful else "local changes"


def _summary_from_paths(change_type: str, paths: list[str]) -> str:
    noun = _path_noun(paths)
    return f"{_summary_verb(change_type)} {noun}"


def _summary_verb(change_type: str) -> str:
    return {
        "docs": "document",
        "feat": "add",
        "fix": "fix",
        "perf": "improve",
        "refactor": "refactor",
        "test": "cover",
    }.get(change_type, "update")


def _path_noun(paths: list[str]) -> str:
    if not paths:
        return "review remediation"
    counts: dict[str, int] = {}
    for path_str in paths:
        counts[path_str] = counts.get(path_str, 0) + 1
    dominant_str = max(counts, key=lambda path_str: (counts[path_str], path_str))
    path = Path(dominant_str)
    stem = path.stem.replace("_", " ").replace("-", " ")
    if (
        len(path.parts) >= 3
        and path.parts[0] == "src"
        and path.parts[1] == "code_review_loop"
    ):
        if len(path.parts) == 3:
            return stem
        package_part = path.parts[2].replace("_", " ").replace("-", " ")
        return f"{stem} in {package_part}"
    if len(path.parts) >= 2:
        return f"{stem} in {path.parts[0]}"
    return stem


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower().replace("_", "-")).strip("-")
    return slug or "local"


def _is_low_signal_scope(scope: str, *, change_type: str) -> bool:
    if not scope:
        return True
    if len(scope) == 1:
        return True
    return scope == change_type or (change_type == "test" and scope == "tests")


def _summary_trigger_words(verb: str) -> set[str]:
    return {
        "add": {
            "add",
            "adds",
            "added",
            "enable",
            "enables",
            "enabled",
            "support",
            "supports",
            "supported",
            "new",
        },
        "cover": {
            "add",
            "adds",
            "added",
            "coverage",
            "cover",
            "covers",
            "covered",
            "test",
            "tests",
        },
        "document": {"document", "documents", "documented", "docs", "new"},
        "fix": {
            "fix",
            "fixes",
            "fixed",
            "preserve",
            "preserves",
            "preserved",
            "avoid",
            "avoids",
            "avoided",
            "prevent",
            "prevents",
            "prevented",
            "restore",
            "restores",
            "restored",
        },
        "improve": {
            "improve",
            "improves",
            "improved",
            "performance",
            "faster",
            "speed",
            "latency",
        },
        "refactor": {
            "refactor",
            "refactors",
            "refactored",
            "extract",
            "extracts",
            "extracted",
            "split",
            "splits",
            "restructure",
            "restructures",
            "restructured",
            "decompose",
            "decomposes",
            "decomposed",
        },
        "update": {"update", "updates", "updated"},
    }.get(verb, {verb})


def _all_summary_trigger_words() -> set[str]:
    words: set[str] = set()
    for verb in ("add", "cover", "document", "fix", "improve", "refactor", "update"):
        words.update(_summary_trigger_words(verb))
    return words


def _display_timeout(value: float | None) -> str:
    return "inherit" if value is None else f"{value:g}"


def format_commit_hook_failure_for_remediation(exc: phase_support.CommitFailed) -> str:
    return "\n".join(
        [
            "Commit hook failure from the previous RevRem iteration.",
            "",
            "Treat this as a verification failure. Remediate the underlying cause,",
            "preserve staged work, and do not bypass hooks unless the operator explicitly",
            "configured that policy.",
            "",
            f"Commit artifact: {exc.artifact_path}",
            "",
            "git commit output:",
            prompts_composer.trim_for_prompt(exc.output, 20_000),
        ]
    ).strip()


class CommitAdapter:
    """Implements CommitHarness via the in-module ``run_commit`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        status = run_commit(
            self._config,
            ctx.runner,
            request.iteration,
            retrying=request.retrying,
            ctx=ctx,
        )
        return CommitOutcome(
            status=cast(Literal["committed", "skipped", "skipped_no_changes"], status)
        )
