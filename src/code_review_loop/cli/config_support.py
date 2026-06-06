"""Filesystem helpers for CLI config assembly."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from code_review_loop.core.review_interpretation import actionable_review_output
from code_review_loop.repo_roots import lexical_git_repo_root as _lexical_git_repo_root


@dataclass(frozen=True)
class PendingReviewCandidate:
    path: Path
    run_dir: Path
    final_status: str | None
    stopped_reason: str | None
    error: str | None
    excerpt: str


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


def resolve_initial_review_file(
    value: str | None,
    search_root: Path,
    *,
    current_git_state: dict[str, object] | None = None,
) -> Path | None:
    if value is None:
        return None
    if value != "latest":
        return Path(value)

    candidates: list[tuple[float, str, Path | None]] = []
    for run_dir in _latest_run_dirs(search_root):
        summary = _read_run_summary(run_dir)
        if not _git_state_is_compatible(summary, current_git_state):
            continue
        review_paths = _usable_run_review_paths(run_dir, search_root, summary)
        if _run_is_resolved(summary):
            candidates.append(
                (_run_sort_time(run_dir, review_paths), run_dir.name, None)
            )
            continue
        if not review_paths:
            continue
        latest_review = review_paths[-1]
        candidates.append(
            (_run_sort_time(run_dir, review_paths), run_dir.name, latest_review)
        )
    candidates.sort()
    if not candidates:
        return None
    return candidates[-1][2]


def find_pending_review_candidate(
    search_root: Path,
    *,
    current_git_state: dict[str, object] | None = None,
) -> PendingReviewCandidate | None:
    candidates: list[tuple[float, str, PendingReviewCandidate | None]] = []
    for run_dir in _latest_run_dirs(search_root):
        summary = _read_run_summary(run_dir)
        if not _git_state_is_compatible(summary, current_git_state):
            continue
        review_paths = _usable_run_review_paths(run_dir, search_root, summary)
        if _run_is_resolved(summary):
            candidates.append(
                (_run_sort_time(run_dir, review_paths), run_dir.name, None)
            )
            continue
        if not review_paths:
            continue
        latest_review = review_paths[-1]
        candidates.append(
            (
                _run_sort_time(run_dir, review_paths),
                run_dir.name,
                PendingReviewCandidate(
                    path=latest_review,
                    run_dir=run_dir,
                    final_status=_optional_summary_str(summary, "final_status"),
                    stopped_reason=_optional_summary_str(summary, "stopped_reason"),
                    error=_optional_summary_str(summary, "error"),
                    excerpt=_review_excerpt(latest_review, summary),
                ),
            )
        )
    candidates.sort()
    if not candidates:
        return None
    return candidates[-1][2]


def current_git_state_for_latest(cwd: Path, base: str) -> dict[str, object] | None:
    if lexical_git_repo_root(cwd) is None:
        return None
    head = _git_stdout(cwd, ["rev-parse", "HEAD"])
    base_commit = _git_stdout(cwd, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    merge_base = (
        _git_stdout(cwd, ["merge-base", "HEAD", base])
        if base_commit is not None
        else None
    )
    return {
        "head": head,
        "base": base,
        "base_commit": base_commit,
        "merge_base": merge_base,
        "available": head is not None and base_commit is not None,
    }


def _git_stdout(cwd: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _latest_run_dirs(search_root: Path) -> list[Path]:
    run_dirs: list[Path] = []
    if search_root.is_dir():
        run_dirs.append(search_root)
        run_dirs.extend(path for path in search_root.iterdir() if path.is_dir())
    return run_dirs


def _read_run_summary(run_dir: Path) -> dict[str, object]:
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return summary if isinstance(summary, dict) else {}


def _usable_run_review_paths(
    run_dir: Path, search_root: Path, summary: dict[str, object]
) -> list[Path]:
    paths: list[Path] = []
    artifact_paths = summary.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        reviews = artifact_paths.get("reviews")
        if isinstance(reviews, list):
            for item in reviews:
                if isinstance(item, str):
                    path = _resolve_summary_path(item, run_dir, search_root)
                    if path is not None:
                        paths.append(path)
    paths.extend(run_dir.glob("review-*.txt"))
    paths.append(run_dir / "review-final.txt")
    usable = {
        path.resolve()
        for path in paths
        if _is_generated_review_artifact(path) and review_final_is_usable(path)
    }
    return sorted(usable, key=lambda path: (path.stat().st_mtime, path.name, str(path)))


def _resolve_summary_path(value: str, run_dir: Path, search_root: Path) -> Path | None:
    path = Path(value)
    candidates = (
        [path] if path.is_absolute() else [run_dir / path, search_root / path, path]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _is_generated_review_artifact(path: Path) -> bool:
    name = path.name
    return name == "review-final.txt" or re.fullmatch(r"review-\d+\.txt", name) is not None


def _optional_summary_str(summary: dict[str, object], key: str) -> str | None:
    value = summary.get(key)
    return value if isinstance(value, str) and value else None


def _review_excerpt(path: Path, summary: dict[str, object]) -> str:
    excerpt = _optional_summary_str(summary, "latest_review_excerpt")
    if excerpt:
        return excerpt
    try:
        return actionable_review_output(path.read_text(encoding="utf-8")).strip()
    except OSError:
        return ""


def _run_sort_time(run_dir: Path, review_paths: list[Path]) -> float:
    times: list[float] = []
    for path in [run_dir / "summary.json", *review_paths, run_dir]:
        try:
            times.append(path.stat().st_mtime)
        except FileNotFoundError:
            continue
    return max(times) if times else 0.0


def _run_is_resolved(summary: dict[str, object]) -> bool:
    return summary.get("final_status") == "clear"


def _git_state_is_compatible(
    summary: dict[str, object],
    current_git_state: dict[str, object] | None,
) -> bool:
    if current_git_state is None or current_git_state.get("available") is not True:
        return True
    previous = summary.get("git_state")
    if not isinstance(previous, dict) or previous.get("available") is not True:
        return False
    for key in ("head", "base", "base_commit", "merge_base"):
        current_value = current_git_state.get(key)
        previous_value = previous.get(key)
        if (
            current_value is not None
            and previous_value is not None
            and current_value != previous_value
        ):
            return False
    return True


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
