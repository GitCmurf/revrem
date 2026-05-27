"""Artifact ignore-file helpers shared by CLI config and runner setup."""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from code_review_loop.config import LoopConfig


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
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


@contextmanager
def _exclusive_lock_file(path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_dir = path.with_name(f"{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_dir}") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.rmdir(lock_dir)


def ensure_default_artifact_ignore(config: LoopConfig) -> None:
    artifact_dir = config.artifact_dir if config.artifact_dir.is_absolute() else config.cwd / config.artifact_dir
    default_runs_dir = config.cwd / ".revrem" / "runs"
    try:
        artifact_dir.relative_to(default_runs_dir)
    except ValueError:
        return
    repo_root = lexical_git_repo_root(config.cwd)
    if repo_root == Path(tempfile.gettempdir()).resolve():
        repo_root = None
    ignore_path = git_info_exclude_path(repo_root) if repo_root is not None else None
    if ignore_path is not None and repo_root is not None:
        ignore_entry = f"{default_runs_dir.relative_to(repo_root).as_posix()}/"
    else:
        ignore_entry = "runs/"
    ignore_path = ignore_path or (config.cwd / ".revrem" / ".gitignore")
    ignore_path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock_file(ignore_path), ignore_path.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        existing = handle.read()
        existing_entries = set(existing.splitlines())
        if ignore_entry in existing_entries:
            return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        handle.seek(0)
        handle.truncate()
        handle.write(f"{existing}{ignore_entry}\n")
