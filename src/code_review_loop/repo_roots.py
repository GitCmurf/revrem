"""Repository-root discovery with temp-root guardrails."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def temp_root_candidates() -> set[Path]:
    roots = {Path(tempfile.gettempdir()).resolve()}
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        roots.add(Path(tmpdir).resolve())
    else:
        roots.add(Path("/tmp").resolve())
    candidates: set[Path] = set()
    for root in roots:
        # Excluding ancestors is intentional: an ambient /tmp/.git should not
        # make every temporary test directory look like a repository.
        candidates.add(root)
        candidates.update(root.parents)
    return candidates


def lexical_git_repo_root(start: Path, *, exclude_temp_roots: bool = True) -> Path | None:
    """Return the nearest lexical git root, ignoring system temp roots by default."""
    current = start.resolve()
    excluded = temp_root_candidates() if exclude_temp_roots else set()
    for candidate in (current, *current.parents):
        if exclude_temp_roots and candidate in excluded:
            continue
        if (candidate / ".git").exists():
            return candidate
    return None


def repo_root_or_cwd(cwd: Path) -> Path:
    return lexical_git_repo_root(cwd) or cwd.resolve()
