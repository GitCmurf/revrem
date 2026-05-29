"""Runtime exceptions and operator-facing summary formatting."""

from __future__ import annotations

import copy
import ntpath
import posixpath
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from code_review_loop.core.outcome import OutcomeFailed, RunOutcome
from code_review_loop.core.ports import CommandResult

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


@dataclass(frozen=True)
class RunnerResult:
    """Typed private runner result with an explicit summary projection."""

    summary: Mapping[str, object]
    outcome: RunOutcome

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy(dict(self.summary))


class RunLoopFailed(RuntimeError):
    """Raised when a bounded loop finishes with an expected step failure."""

    def __init__(self, summary: dict[str, object], message: str, *, outcome: OutcomeFailed):
        super().__init__(message)
        self._summary = copy.deepcopy(summary)
        self.outcome = outcome

    @property
    def summary(self) -> dict[str, object]:
        return copy.deepcopy(self._summary)


def _artifact_filename(path: object) -> str:
    if isinstance(path, PurePath):
        return path.name
    text = str(path)
    return ntpath.basename(posixpath.basename(text))


def format_terminal_summary(summary: dict[str, object]) -> str:
    artifact_dir = str(summary.get("artifact_dir") or "")
    status = str(summary.get("final_status") or "unknown")
    reason = str(summary.get("stopped_reason") or "unknown")
    lines = [
        f"Review-remediation loop: {status} ({reason})",
        f"Artifacts: {artifact_dir}",
    ]
    history_path = summary.get("history_path")
    if history_path:
        lines.append(f"Run history: {history_path}")
    phase_config = summary.get("phase_config")
    if isinstance(phase_config, dict):
        lines.append(f"Phase config: {_phase_config_summary(phase_config)}")

    iterations = summary.get("iterations")
    if isinstance(iterations, list) and iterations:
        lines.append("Iterations:")
        for item in iterations:
            if not isinstance(item, dict):
                continue
            iteration = item.get("iteration")
            review_status = item.get("review_status", "unknown")
            check_failures = item.get("check_failures")
            check_text = "checks not run" if check_failures is None else f"check failures: {check_failures}"
            failed = " remediation failed" if item.get("remediation_failed") else ""
            commit_status = item.get("commit_status")
            commit_text = f", commit={commit_status}" if commit_status else ""
            commit_failed = " commit failed" if item.get("commit_failed") else ""
            lines.append(
                f"  {iteration}: review={review_status}, {check_text}{failed}"
                f"{commit_text}{commit_failed}"
            )

    artifact_paths = summary.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        reviews = artifact_paths.get("reviews")
        last_messages = artifact_paths.get("last_messages")
        checks = artifact_paths.get("checks")
        if isinstance(reviews, list) and reviews:
            lines.append(f"Latest review: {reviews[-1]}")
            if status == "findings":
                lines.append(f"Continue command: {_resume_command(summary, str(reviews[-1]))}")
        if isinstance(last_messages, list) and last_messages:
            lines.append(f"Latest remediation summary: {last_messages[-1]}")
        if isinstance(checks, list) and checks:
            latest_checks = _latest_iteration_checks([str(path) for path in checks])
            lines.append("Latest check outputs:")
            for path in latest_checks:
                lines.append(f"  - {path}")
        commits = artifact_paths.get("commits")
        if isinstance(commits, list) and commits:
            commit_outputs = [
                str(path)
                for path in commits
                if re.fullmatch(r"commit-\d+\.txt", _artifact_filename(path))
            ]
            lines.append(f"Latest commit artifact: {(commit_outputs or commits)[-1]}")
        summary_path = artifact_paths.get("summary")
        if summary_path:
            lines.append(f"JSON summary: {summary_path}")

    excerpt = str(summary.get("latest_review_excerpt") or "").strip()
    if excerpt and status != "clear":
        lines.append("")
        lines.append("Latest actionable review output:")
        lines.append(excerpt)

    if summary.get("error"):
        lines.append("")
        lines.append(f"Error: {summary['error']}")

    unexpected = summary.get("unexpected_behaviors")
    if isinstance(unexpected, list) and unexpected:
        lines.append("")
        lines.append("WARNING: unexpected loop behavior detected.")
        lines.append("Review status was classified as unknown during this run.")
        bug_report_path = summary.get("bug_report_path")
        if bug_report_path:
            lines.append(f"Bug report details: {bug_report_path}")

    return "\n".join(lines)


def _phase_config_summary(phase_config: dict[object, object]) -> str:
    parts: list[str] = []
    for phase in ("review", "triage", "remediation", "commit_message"):
        value = phase_config.get(phase)
        if not isinstance(value, dict):
            continue
        if value.get("enabled") is False:
            parts.append(f"{phase}=disabled")
            continue
        details = [
            str(item)
            for item in (
                value.get("harness"),
                value.get("model"),
                f"effort={value['reasoning_effort']}" if value.get("reasoning_effort") else None,
                f"timeout={value['timeout_seconds']}" if value.get("timeout_seconds") is not None else None,
            )
            if item
        ]
        parts.append(f"{phase}({', '.join(details)})")
    return "; ".join(parts) if parts else "not recorded"


def _resume_command(summary: dict[str, object], review_path: str) -> str:
    command = ["./.venv/bin/revrem"]
    base = summary.get("base")
    if isinstance(base, str) and base:
        command.extend(["--base", base])
    profile = summary.get("profile")
    if isinstance(profile, str) and profile:
        command.extend(["--profile", profile])
    command.extend(["--initial-review-file", review_path])
    if summary.get("commit_no_verify") is False and summary.get("commit_on_hook_failure"):
        command.extend(["--commit-on-hook-failure", str(summary["commit_on_hook_failure"])])
    return " ".join(command)


def _latest_iteration_checks(paths: list[str]) -> list[str]:
    latest_iteration = -1
    parsed: list[tuple[int, str]] = []
    for path in paths:
        match = re.search(r"check-(\d+)-\d+\.txt$", _artifact_filename(path))
        if not match:
            continue
        iteration = int(match.group(1))
        latest_iteration = max(latest_iteration, iteration)
        parsed.append((iteration, path))
    if latest_iteration < 0:
        return paths[-2:]
    return [path for iteration, path in parsed if iteration == latest_iteration]
