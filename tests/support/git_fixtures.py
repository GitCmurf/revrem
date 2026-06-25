"""Shared git-repo fixtures for TUI tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def init_repo(repo: Path, *, extra_files: dict[str, str] | None = None) -> Path:
    """Create a committed git repo with a README plus any ``extra_files``.

    Every file is committed in the initial commit so diff-based review sees a
    clean working tree. Returns ``repo`` for convenience.
    """
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    files = {"README.md": "# Fixture\n", **(extra_files or {})}
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo
