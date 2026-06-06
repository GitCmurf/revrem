"""Git preflight gateway (REVREM-TASK-003 Wave C3a step 2).

Hosts ``run_git_preflight``, used by both the review preflight and the resume
precondition checks.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from code_review_loop.adapters import phase_support
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.git_context_cache import GitContextCache


def run_git_preflight(cwd: Path, args: Sequence[str]) -> CommandResult:
    command = ["git", *args]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command,
            -1,
            stdout=phase_support._timeout_stream_text(exc.output),
            stderr=phase_support._timeout_stream_text(exc.stderr),
        )
    return CommandResult(
        command,
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def git_preflight_stdout(cwd: Path, args: Sequence[str]) -> str | None:
    result = run_git_preflight(cwd, args)
    if result.returncode != 0:
        return None
    if result.stdout is None:
        return None
    value = result.stdout.strip()
    return value or None


def git_state_for_resume(config: LoopConfig) -> dict[str, object]:
    if phase_support.lexical_git_repo_root(config.cwd) is None:
        return {
            "head": None,
            "base": config.base,
            "base_commit": None,
            "merge_base": None,
            "available": False,
        }
    head = git_preflight_stdout(config.cwd, ["rev-parse", "HEAD"])
    base_commit = git_preflight_stdout(config.cwd, ["rev-parse", "--verify", f"{config.base}^{{commit}}"])
    merge_base = (
        git_preflight_stdout(config.cwd, ["merge-base", "HEAD", config.base])
        if base_commit is not None
        else None
    )
    return {
        "head": head,
        "base": config.base,
        "base_commit": base_commit,
        "merge_base": merge_base,
        "available": head is not None and base_commit is not None,
    }


def cached_base_commit(
    cache: GitContextCache | None,
    cwd: Path,
    base: str,
) -> CommandResult:
    """Return ``git rev-parse --verify <base>{commit}`` from the cache when
    available, otherwise run the command and store the result.
    """
    key = (str(cwd), base)
    if cache is not None and key in cache.base_commit:
        stdout = cache.base_commit[key]
        return CommandResult(
            ["git", "rev-parse", "--verify", f"{base}^{{commit}}"],
            0 if stdout else 1,
            stdout=stdout,
        )
    result = run_git_preflight(cwd, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    if cache is not None and result.returncode == 0:
        cache.base_commit[key] = result.stdout.strip()
    return result


def cached_merge_base(
    cache: GitContextCache | None,
    cwd: Path,
    head: str,
    base: str,
) -> CommandResult:
    """Return ``git merge-base HEAD <base>`` from the cache when available."""
    key = (str(cwd), head, base)
    if cache is not None and key in cache.merge_base:
        stdout = cache.merge_base[key]
        return CommandResult(
            ["git", "merge-base", "HEAD", base],
            0 if stdout else 1,
            stdout=stdout,
        )
    result = run_git_preflight(cwd, ["merge-base", "HEAD", base])
    if cache is not None and result.returncode == 0:
        cache.merge_base[key] = result.stdout.strip()
    return result


def cached_diff_base_head(
    cache: GitContextCache | None,
    cwd: Path,
    head: str,
    base: str,
    *,
    stat: bool = False,
    name_status: bool = False,
) -> CommandResult:
    """Return ``git diff [options] <base>...HEAD`` from the cache when the
    ``(cwd, head, base)`` triple is unchanged, otherwise run it and update
    the cache. Callers must pass the live HEAD SHA (do not cache it) so the
    per-iteration diff is recomputed whenever remediation advances HEAD.
    """
    diff_args: list[str] = ["diff"]
    if stat:
        diff_args.append("--stat")
    if name_status:
        diff_args.append("--name-status")
    key = (str(cwd), head, base)
    bucket: dict[tuple[str, str, str], str]
    if stat:
        bucket = cache.base_head_diff_stat if cache is not None else {}
    elif name_status:
        bucket = cache.base_head_diff_name_status if cache is not None else {}
    else:
        bucket = cache.base_head_diff if cache is not None else {}
    if cache is not None and key in bucket:
        stdout = bucket[key]
        return CommandResult(
            ["git", *diff_args, f"{base}...HEAD"],
            0,
            stdout=stdout,
        )
    result = run_git_preflight(cwd, [*diff_args, f"{base}...HEAD"])
    if cache is not None and result.returncode == 0:
        bucket[key] = result.stdout
    return result
