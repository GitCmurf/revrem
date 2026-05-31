"""Filesystem helpers for CLI config assembly."""

from __future__ import annotations

import json
from pathlib import Path

from code_review_loop.core.review_interpretation import actionable_review_output
from code_review_loop.repo_roots import lexical_git_repo_root as _lexical_git_repo_root


def git_info_exclude_path(cwd: Path) -> Path | None:
    git_path = cwd / ".git"
    if git_path.is_dir():
        return git_path / "info" / "exclude"
    if not git_path.is_file():
        return None
    content = git_path.read_text(encoding="utf-8", errors="replace").strip()
    if not content.startswith("gitdir:"):
        return None
    path_str = content.split(":", 1)[1].strip()
    if not path_str:
        return None
    git_dir = Path(path_str)
    if not git_dir.is_absolute():
        git_dir = git_path.parent / git_dir
    if git_dir.parent.name == "worktrees":
        return git_dir.parent.parent / "info" / "exclude"
    return git_dir / "info" / "exclude"


def lexical_git_repo_root(start: Path) -> Path | None:
    return _lexical_git_repo_root(start)


def resolve_initial_review_file(value: str | None, search_root: Path) -> Path | None:
    if value is None:
        return None
    if value != "latest":
        return Path(value)

    candidates: list[tuple[float, str, Path]] = []
    for path in (
        search_root / "review-final.txt",
        *search_root.glob("*/review-final.txt"),
    ):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if path.is_file() and review_final_is_usable(path):
            candidates.append((stat.st_mtime, path.parent.name, path))
    candidates.sort()
    if not candidates:
        return None
    latest = candidates[-1][2]
    if review_final_is_resolved(latest):
        return None
    return latest


def review_final_is_resolved(review_path: Path) -> bool:
    summary_path = review_path.with_name("summary.json")
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(summary, dict) and summary.get("final_status") == "clear"


def review_final_is_usable(review_path: Path) -> bool:
    try:
        review_text = actionable_review_output(review_path.read_text(encoding="utf-8")).strip()
    except OSError:
        return False
    if not review_text:
        return False
    return not review_text.startswith("DRY_RUN")
