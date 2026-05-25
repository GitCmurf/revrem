"""Application service boundary for running RevRem review loops.

This module is the non-CLI entrypoint for callers that want to execute or
resume a review loop without depending on command parsing or terminal command
modules. The current implementation delegates to the runner while ownership is
being moved behind this boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import budgets, resume, runner
from code_review_loop.clock import SYSTEM_CLOCK, Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity
from code_review_loop.runtime import RunLoopFailed, format_terminal_summary

Runner = runner.Runner


def run_review_loop(
    config: LoopConfig,
    process_runner: Runner = runner.default_runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
) -> dict[str, object]:
    """Run one bounded review/remediation loop and return the summary payload."""
    return runner.run_loop(
        config,
        process_runner,
        clock=clock,
        identity=identity,
        budget_state=budget_state,
    )


def resume_review_loop(run_dir: Path, *, cwd: Path | None = None) -> dict[str, object]:
    """Resume a previous review loop run from ``run_dir``."""
    summary_path = run_dir / "summary.json"
    try:
        summary_text = summary_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"summary.json not found in run directory: {run_dir}") from exc
    summary = json.loads(summary_text)
    if not isinstance(summary, dict):
        raise ValueError("summary.json must contain a JSON object")
    budget_issues = resume.resume_budget_ceiling_issues(summary)
    if budget_issues:
        raise ValueError("; ".join(issue.message for issue in budget_issues))
    config, resumed_budget_state = resume.resume_loop_config(
        summary,
        run_dir=run_dir,
        cwd=cwd,
    )
    return run_review_loop(config, budget_state=resumed_budget_state)


def append_run_history(summary: dict[str, object], config: LoopConfig) -> Path:
    """Append the run summary to the operator's local run history."""
    return runner.append_run_history(summary, config)


__all__ = [
    "CommandResult",
    "RunLoopFailed",
    "Runner",
    "append_run_history",
    "format_terminal_summary",
    "resume_review_loop",
    "run_review_loop",
]
