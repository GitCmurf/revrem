"""Runtime guardrails for watched RevRem runs."""

from __future__ import annotations

from code_review_loop.adapters.commit import git_worktree_status_command_for_commit
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import EngineState
from code_review_loop.core.ports import RunContext
from code_review_loop.git_status import non_artifact_status_lines
from code_review_loop.repo_roots import lexical_git_repo_root


def assert_worktree_stable_before_remediation(
    config: LoopConfig,
    ctx: RunContext,
    engine_state: EngineState,
    *,
    expected_head: str | None,
) -> None:
    """Stop auto-commit remediation if review/triage raced checkout changes."""
    if not config.commit_after_remediation or config.dry_run:
        return
    if lexical_git_repo_root(config.cwd) is None:
        return
    if engine_state.acc.pending_check_failures or engine_state.acc.commit_retry:
        return
    if engine_state.acc.inner_check_retry_count:
        return
    current = current_head(config, ctx)
    if expected_head is not None and current and current != expected_head:
        raise RuntimeError(
            "worktree changed during run before remediation: HEAD moved from "
            f"{expected_head} to {current}. RevRem preserved the review "
            "artifact and stopped before spending remediation work; rerun after "
            "reviewing the concurrent commit."
        )
    dirty_lines = current_non_artifact_status_lines(config, ctx)
    if dirty_lines:
        shown = "\n".join(dirty_lines[:20])
        more = "" if len(dirty_lines) <= 20 else f"\n... and {len(dirty_lines) - 20} more"
        raise RuntimeError(
            "worktree changed during run before remediation. RevRem preserved "
            "the review artifact and stopped before spending remediation work. "
            "Commit, stash, ignore, or remove these concurrent changes first:\n"
            f"{shown}{more}"
        )


def current_head(config: LoopConfig, ctx: RunContext) -> str | None:
    result = ctx.runner(
        ["git", "rev-parse", "HEAD"],
        config.cwd,
        None,
        config.timeout_seconds,
    )
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def current_non_artifact_status_lines(
    config: LoopConfig, ctx: RunContext
) -> list[str]:
    result = ctx.runner(
        git_worktree_status_command_for_commit(config),
        config.cwd,
        None,
        config.timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError("git worktree status check failed before remediation could start")
    return non_artifact_status_lines(config, result.stdout)
