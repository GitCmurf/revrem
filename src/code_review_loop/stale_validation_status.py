"""Git status snapshots for stale-review validation."""

from __future__ import annotations

from code_review_loop import git_status
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import RunContext
from code_review_loop.repo_roots import lexical_git_repo_root


def non_artifact_status_snapshot(
    config: LoopConfig,
    ctx: RunContext,
) -> tuple[str, ...]:
    if lexical_git_repo_root(config.cwd) is None:
        return ()
    result = ctx.runner(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        config.cwd,
        None,
        config.timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError("stale review validation could not snapshot git status")
    return git_status.non_artifact_status_entries_from_status_z(config, result.stdout)


def dirty_message(
    config: LoopConfig,
    ctx: RunContext,
    before: tuple[str, ...] | None,
) -> str:
    if before is None:
        return ""
    after = non_artifact_status_snapshot(config, ctx)
    if after == before:
        return ""
    before_set = set(before)
    after_set = set(after)
    added = sorted(after_set - before_set)
    removed = sorted(before_set - after_set)
    lines = ["stale review validation emitted resolved marker but changed non-artifact git status"]
    if added:
        lines.append("Added/changed status entries:")
        lines.extend(f"  + {entry}" for entry in added)
    if removed:
        lines.append("Removed status entries:")
        lines.extend(f"  - {entry}" for entry in removed)
    return "\n".join(lines)
