"""Helpers for interpreting porcelain git status output."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
    artifact_prefixes = {".revrem/"}
    rel_artifact = _relative_artifact_dir(config)
    if rel_artifact is not None:
        rel_text = rel_artifact.as_posix().rstrip("/")
        if rel_text:
            artifact_prefixes.add(rel_text)
            artifact_prefixes.add(f"{rel_text}/")
    return all(
        any(part == prefix.rstrip("/") or part.startswith(prefix) for prefix in artifact_prefixes)
        for part in path_parts
    )


def _relative_artifact_dir(config: LoopConfig) -> Path | None:
    try:
        return config.artifact_dir.resolve().relative_to(config.cwd.resolve())
    except ValueError:
        return None
