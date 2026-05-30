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


def git_reset_artifact_command_for_commit(config: LoopConfig, repo_root: Path | None) -> list[str] | None:
    if repo_root is None:
        return None
    artifact_rel = commit_artifact_relative_path(config, repo_root)
    if artifact_rel is None:
        return None
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

    repo_root = git_repo_root(config, runner)
    if repo_root is not None:
        reject_artifact_dir_at_repo_root(config, repo_root)
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

    reset_command = git_reset_artifact_command_for_commit(config, repo_root)
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
    fallback_context = commit_message_fallback_context(config, iteration)
    fallback = deterministic_commit_message(
        iteration,
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
    command = phase_support.build_commit_message_command(config)
    prompt_root = config.commit_message_prompt or phase_support.DEFAULT_COMMIT_MESSAGE_PROMPT
    prompt = f"{prompt_root}\n{prompts_composer.trim_for_prompt(context, config.max_remediation_input_chars)}"
    command, prompt_input = harnesses.prepare_prompt_invocation(
        config.commit_message_harness,
        command,
        prompt,
    )
    phase_support.ensure_model_budget(config, phase="commit-message", iteration=iteration, ctx=ctx)
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
    iteration: int,
    *,
    staged_paths: list[str] | None = None,
    context: str = "",
) -> str:
    paths = staged_paths or []
    change_type = _commit_type(paths, context=context)
    scope = _commit_scope(paths, change_type=change_type)
    summary = _commit_summary(change_type, paths, context=context)
    if scope:
        return f"{change_type}({scope}): {summary} (RevRem)"
    return f"{change_type}: {summary} (RevRem)"


def _commit_scope(paths: list[str], *, change_type: str) -> str:
    if not paths:
        return "review"
    path_parts = [Path(path).parts for path in paths if Path(path).parts]
    if not path_parts:
        return "review"
    first_parts = [parts[0] for parts in path_parts]
    counts = {part: first_parts.count(part) for part in set(first_parts)}
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
    counts = {part: candidates.count(part) for part in set(candidates)}
    return _slug(max(counts, key=lambda part: (counts[part], part)))


def _commit_type(paths: list[str], *, context: str = "") -> str:
    if paths and all(path.startswith("docs/") or path.endswith(".md") for path in paths):
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
    if _contains_any(leading_context, (r"\bperformance\b", r"\bcach(?:e|ing)\b", r"\bfaster\b", r"\bspeed\b", r"\blatency\b")):
        return "perf"
    if _contains_any(
        leading_context,
        (r"\brefactor(?:s|ed)?\b", r"\bextract(?:s|ed)?\b", r"\bsplit(?:s)?\b", r"\brestructure(?:s|d)?\b", r"\bdecompose(?:s|d)?\b"),
    ):
        return "refactor"
    if _contains_any(
        leading_context,
        (r"\badd(?:s|ed)?\b", r"\benable(?:s|d)?\b", r"\bsupport(?:s|ed)?\b", r"\bnew\b", r"\bfeature(?:s)?\b"),
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
    dominant = max(paths, key=lambda path: (paths.count(path), path))
    path = Path(dominant)
    stem = path.stem.replace("_", " ").replace("-", " ")
    if len(path.parts) >= 3 and path.parts[0] == "src" and path.parts[1] == "code_review_loop":
        if len(path.parts) == 3:
            return stem
        package_part = path.parts[2].replace("_", " ").replace("-", " ")
        if package_part not in stem:
            return f"{package_part} {stem}"
    if len(path.parts) >= 3 and path.parts[0] == "src":
        package_part = path.parts[-2].replace("_", " ").replace("-", " ")
        if package_part not in stem:
            return f"{package_part} {stem}"
    if len(path.parts) >= 2 and path.parts[0] == "tests":
        return stem.removeprefix("test ")
    return stem or "local changes"


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
        "add": {"add", "adds", "added", "enable", "enables", "enabled", "support", "supports", "supported", "new"},
        "cover": {"add", "adds", "added", "coverage", "cover", "covers", "covered", "test", "tests"},
        "document": {"document", "documents", "documented", "docs", "new"},
        "fix": {"fix", "fixes", "fixed", "preserve", "preserves", "preserved", "avoid", "avoids", "avoided", "prevent", "prevents", "prevented", "restore", "restores", "restored"},
        "improve": {"improve", "improves", "improved", "performance", "faster", "speed", "latency"},
        "refactor": {"refactor", "refactors", "refactored", "extract", "extracts", "extracted", "split", "splits", "restructure", "restructures", "restructured", "decompose", "decomposes", "decomposed"},
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
        return CommitOutcome(status=cast(Literal["committed", "skipped", "skipped_no_changes"], status))
