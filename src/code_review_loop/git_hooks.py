"""Git hook path resolution helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path


def default_hooks_dir(cwd: Path) -> Path | None:
    """Return Git's resolved default hook directory for ``cwd``.

    Uses Git's own path resolution so linked worktrees and submodules with a
    ``.git`` file are handled the same way as ordinary repositories.
    """
    return _git_path(cwd, "hooks")


def configured_hooks_path(cwd: Path) -> Path | None:
    """Return ``core.hooksPath`` resolved relative to a Git worktree root.

    Non-repository directories do not get a configured hooks path, even if a
    global Git config defines one.
    """
    root = worktree_root(cwd)
    if root is None:
        return None
    raw = _git_config_path(cwd, "core.hooksPath")
    if raw is None:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def worktree_root(cwd: Path) -> Path | None:
    completed = _run_git(cwd, "rev-parse", "--show-toplevel")
    if completed is None or completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return Path(value) if value else None


def _git_path(cwd: Path, path: str) -> Path | None:
    completed = _run_git(cwd, "rev-parse", "--git-path", path)
    if completed is None or completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    if not value:
        return None
    resolved = Path(value)
    return resolved if resolved.is_absolute() else cwd.resolve() / resolved


def _git_config_path(cwd: Path, key: str) -> str | None:
    completed = _run_git(cwd, "config", "--path", "--get", key)
    if completed is None or completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd.resolve(),
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None
