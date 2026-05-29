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

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from code_review_loop import artifacts, harnesses, prompts_composer
from code_review_loop.adapters import phase_support
from code_review_loop.core.ports import CommandResult, CommitOutcome, CommitRequest, RunContext
from code_review_loop.core.review_interpretation import actionable_review_output

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


def git_add_command_for_commit(_config: LoopConfig) -> list[str]:
    return ["git", "add", "-A"]


def git_worktree_status_command_for_commit(_config: LoopConfig) -> list[str]:
    return ["git", "status", "--porcelain=v1", "--untracked-files=all"]


def git_repo_root(start: Path) -> Path:
    resolved_start = start.resolve()
    for candidate in (resolved_start, *resolved_start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"unable to determine git repository root from {start}")


def commit_artifact_relative_path(config: LoopConfig) -> Path | None:
    repo_root = git_repo_root(config.cwd)
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


def git_reset_artifact_command_for_commit(config: LoopConfig) -> list[str] | None:
    artifact_rel = commit_artifact_relative_path(config)
    if artifact_rel is None:
        return None
    repo_root = git_repo_root(config.cwd)
    # Keep generated loop artifacts out of the staged commit. Resolve artifact
    # paths from the git root so subdirectory invocations can still reset files
    # that live elsewhere inside the same repository.
    return ["git", "-C", str(repo_root), "reset", "--", artifact_rel.as_posix()]


def commit_command_for_message(message: str, *, allow_no_verify: bool = False) -> list[str]:
    command = ["git", "commit"]
    if allow_no_verify:
        command.append("--no-verify")
    command.extend(["-m", message])
    return command


def classify_commit_failure(result: CommandResult) -> str:
    output = phase_support._combined_output(result)
    return "hook_failed" if phase_support.COMMIT_HOOK_FAILURE_RE.search(output) else "commit_failed"


def run_commit(config: LoopConfig, runner: Runner, iteration: int, *, ctx: RunContext, retrying: bool = False) -> str:
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
        phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}.txt", "DRY_RUN commit skipped\n")
        phase_support.progress_event(config, "commit", str(iteration), "skipped", "dry-run", ctx=ctx)
        return "skipped"

    commit_artifact_relative_path(config)
    add_result = runner(
        git_add_command_for_commit(config),
        config.cwd,
        None,
        phase_support.phase_timeout_seconds(config, config.timeout_seconds),
    )
    phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}-add.txt", phase_support._combined_output(add_result))
    if add_result.returncode != 0:
        phase_support.progress_event(config, "commit", str(iteration), "failed", "git add failed", ctx=ctx)
        raise RuntimeError(
            f"git add failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'commit-{iteration}-add.txt'}"
        )

    reset_command = git_reset_artifact_command_for_commit(config)
    if reset_command is not None:
        reset_result = runner(
            reset_command,
            config.cwd,
            None,
            phase_support.phase_timeout_seconds(config, config.timeout_seconds),
        )
        phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}-reset-artifacts.txt", phase_support._combined_output(reset_result))
        if reset_result.returncode != 0:
            phase_support.progress_event(config, "commit", str(iteration), "failed", "git reset artifacts failed", ctx=ctx)
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
        phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}.txt", "No staged changes to commit.\n")
        phase_support.progress_event(config, "commit", str(iteration), "skipped", "no staged changes", ctx=ctx)
        return "skipped_no_changes"
    if diff_quiet.returncode != 1:
        phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}.txt", phase_support._combined_output(diff_quiet))
        phase_support.progress_event(config, "commit", str(iteration), "failed", "git diff --cached --quiet failed", ctx=ctx)
        raise RuntimeError(f"git staged-diff check failed for iteration {iteration}")

    message = commit_message_for_staged_changes(config, runner, iteration, ctx=ctx)
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
        detail = "git commit hook failed" if kind == "hook_failed" else "git commit failed"
        phase_support.progress_event(config, "commit", str(iteration), "failed", detail, ctx=ctx)
        raise phase_support.CommitFailed(
            iteration=iteration,
            kind=kind,
            artifact_path=commit_artifact_path,
            output=commit_output,
        )
    phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}-message.txt", message + "\n")
    phase_support.progress_event(config, "commit", str(iteration), "committed", message, ctx=ctx)
    return "committed"


def commit_message_for_staged_changes(config: LoopConfig, runner: Runner, iteration: int, ctx: RunContext) -> str:
    timeout_seconds = phase_support.phase_timeout_seconds(
        config, config.commit_timeout_seconds
    )
    stat = runner(["git", "diff", "--cached", "--stat"], config.cwd, None, timeout_seconds)
    names = runner(["git", "diff", "--cached", "--name-only"], config.cwd, None, timeout_seconds)
    stat_stdout = stat.stdout or ""
    names_stdout = names.stdout or ""
    staged_paths = [line.strip() for line in names_stdout.splitlines() if line.strip()]
    fallback = deterministic_commit_message(iteration, staged_paths=staged_paths)
    context = "\n".join(
        part
        for part in (
            "Files:",
            names_stdout.strip(),
            "",
            "Stat:",
            stat_stdout.strip(),
        )
        if part is not None
    )
    if not config.commit_message_model:
        return fallback
    command = phase_support.build_commit_message_command(config)
    prompt_root = config.commit_message_prompt or phase_support.DEFAULT_COMMIT_MESSAGE_PROMPT
    prompt = f"{prompt_root}\n{prompts_composer.trim_for_prompt(context, config.max_remediation_input_chars)}"
    command, prompt_input = harnesses.prepare_prompt_invocation(
        config.commit_message_harness,
        command,
        prompt,
    )
    phase_support.ensure_model_budget(config, phase="commit-message", iteration=iteration, ctx=ctx)
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
        ),
        ctx=ctx,
    )
    result = runner(command, config.cwd, prompt_input, timeout_seconds)
    phase_support.write_artifact(config.artifact_dir / f"commit-{iteration}-message-draft.txt", phase_support._combined_output(result))
    phase_support.record_model_charge(config, result, phase="commit-message", iteration=iteration, ctx=ctx)
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
    return phase_support.sanitize_commit_message(
        actionable_review_output(phase_support._combined_output(result)),
        fallback=fallback,
        enforce_revrem_conventional=not config.commit_message_prompt_overridden,
    )


def deterministic_commit_message(iteration: int, *, staged_paths: list[str] | None = None) -> str:
    paths = staged_paths or []
    scope = _commit_scope(paths)
    change_type = _commit_type(paths)
    if scope:
        return f"{change_type}({scope}): apply verified remediation {iteration} (RevRem)"
    return f"{change_type}: apply verified remediation {iteration} (RevRem)"


def _commit_scope(paths: list[str]) -> str:
    if not paths:
        return "review"
    first_parts = [Path(path).parts[0] for path in paths if Path(path).parts]
    if not first_parts:
        return "review"
    counts = {part: first_parts.count(part) for part in set(first_parts)}
    dominant = max(counts, key=lambda part: (counts[part], part))
    scope_map = {
        "src": "core",
        "tests": "tests",
        "docs": "docs",
    }
    return scope_map.get(dominant, dominant.replace("_", "-"))


def _commit_type(paths: list[str]) -> str:
    if paths and all(path.startswith("docs/") or path.endswith(".md") for path in paths):
        return "docs"
    if paths and all(path.startswith("tests/") for path in paths):
        return "test"
    return "fix"


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
        return CommitOutcome(status=cast(Literal["committed", "skipped", "skipped_no_changes"], status))
