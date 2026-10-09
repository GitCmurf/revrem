"""Shared, dependency-free discovery of the newest local run summary.

Both the CLI wizard and the TUI recover settings from persisted run summaries.
Keeping discovery here prevents either UI from depending on the other's private
helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_review_loop import run_history
from code_review_loop.repo_roots import repo_root_or_cwd


@dataclass(frozen=True)
class LastRunSummary:
    summary_path: Path | None
    skipped_reason: str | None = None


def latest_summary(cwd: Path) -> LastRunSummary:
    """Return the newest readable-history summary belonging to ``cwd``'s repo."""
    normalized_cwd = repo_root_or_cwd(cwd)
    for record in run_history.read_history():
        record_cwd = record.get("cwd")
        if not isinstance(record_cwd, str):
            continue
        if repo_root_or_cwd(Path(record_cwd)) != normalized_cwd:
            continue
        summary_path = record.get("summary_path")
        if not isinstance(summary_path, str) or not summary_path:
            return LastRunSummary(None, "newest history record has no summary path")
        path = Path(summary_path)
        if not path.is_absolute():
            path = Path(record_cwd) / path
        if not path.is_file():
            return LastRunSummary(None, f"summary missing: {path}")
        return LastRunSummary(path)
    return LastRunSummary(None)


def current_git_state(cwd: Path, base: str) -> dict[str, object] | None:
    """Read the Git fingerprint used to decide whether review input is stale."""
    from code_review_loop.cli.config_support import current_git_state_for_latest

    return current_git_state_for_latest(cwd, base)


def find_pending_review(
    search_root: Path, *, current_git_state: dict[str, object] | None = None
):
    """Locate the latest reusable review artifact through one shared boundary."""
    from code_review_loop.cli.config_support import find_pending_review_candidate

    return find_pending_review_candidate(
        search_root, current_git_state=current_git_state
    )
