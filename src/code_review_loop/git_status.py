"""Helpers for interpreting porcelain git status output."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from code_review_loop.repo_roots import lexical_git_repo_root

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig


def non_artifact_status_lines(config: LoopConfig, status_stdout: str) -> list[str]:
    """Return non-empty status lines that are outside RevRem artifacts."""
    return [
        line
        for line in status_stdout.splitlines()
        if line.strip() and not is_artifact_status_line(config, line)
    ]


def is_artifact_status_line(config: LoopConfig, line: str) -> bool:
    """Return whether all paths in one porcelain status line are artifacts."""
    path_text = line[3:].strip() if len(line) >= 3 else line.strip()
    if not path_text:
        return True
    path_parts = [part.strip() for part in path_text.split(" -> ") if part.strip()]
    if not path_parts:
        return True
    artifact_roots = _artifact_roots(config)
    return all(
        any(_is_under_path_root(part, root) for root in artifact_roots)
        for part in path_parts
    )


def untracked_paths_from_status_z(status_stdout: str) -> list[str]:
    """Decode ``git status -z`` output and return the untracked paths verbatim.

    ``git status -z`` is the unambiguous, machine-friendly variant of the
    porcelain output. The format is NUL-delimited (rather than LF-delimited)
    and paths are emitted byte-for-byte with no quoting and no escaping. Each
    non-renamed entry looks like ``XY PATH\\0`` where ``XY`` is a 2-character
    status code; the cleanliness check only needs the untracked entries
    (``?? ...``) and ignores renamed/copied entries (``R  \\0ORIG\\0NEW\\0``).

    Returning the decoded paths (not raw lines) is deliberate: callers can
    pass the paths straight to ``git add --intent-to-add -- <path>`` without
    re-parsing the same string and without accidentally forwarding Git's
    surrounding quotes or escapes to a downstream subprocess.
    """
    paths: list[str] = []
    for entry in status_stdout.split("\0"):
        if not entry:
            continue
        if not entry.startswith("?? "):
            continue
        path = entry[3:]
        if path:
            paths.append(path)
    return paths


def is_artifact_path(config: LoopConfig, path: str) -> bool:
    """Return whether a single repo-root-relative path is a RevRem artifact.

    Mirrors :func:`is_artifact_status_line` for callers that already have the
    decoded path in hand (e.g. parsed from ``git status -z`` output) and do
    not want to synthesise a status line just to reuse the line-based check.
    """
    normalized = path.strip().rstrip("/")
    if not normalized:
        return True
    artifact_roots = _artifact_roots(config)
    return any(_is_under_path_root(normalized, root) for root in artifact_roots)


def _artifact_roots(config: LoopConfig) -> set[str]:
    """Return the repo-root-relative path prefixes that count as artifacts.

    ``git status --porcelain`` always emits paths relative to the repository
    root, even when the command is invoked from a subdirectory. We therefore
    whitelist ``.revrem`` and the configured ``artifact_dir`` expressed
    relative to the repository root (falling back to ``config.cwd`` when the
    artifact directory is nested below it but the repository root is not
    reachable from the cwd, e.g. when running outside a git worktree).
    """
    roots: set[str] = {".revrem"}
    repo_root = lexical_git_repo_root(config.cwd)
    bases: list[Path] = []
    if repo_root is not None:
        bases.append(repo_root)
    bases.append(config.cwd.resolve())
    for base in bases:
        rel = _relative_artifact_dir_to(config, base)
        if rel is None:
            continue
        rel_text = rel.as_posix().rstrip("/")
        if rel_text:
            roots.add(rel_text)
    return roots


def _is_under_path_root(path: str, root: str) -> bool:
    normalized = path.strip().rstrip("/")
    normalized_root = root.strip().rstrip("/")
    return normalized == normalized_root or normalized.startswith(f"{normalized_root}/")


def _relative_artifact_dir(config: LoopConfig) -> Path | None:
    return _relative_artifact_dir_to(config, config.cwd)


def _relative_artifact_dir_to(config: LoopConfig, base: Path) -> Path | None:
    try:
        return config.artifact_dir.resolve().relative_to(base.resolve())
    except ValueError:
        return None
