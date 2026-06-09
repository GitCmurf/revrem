"""Application service boundary for running RevRem review loops.

This module is the non-CLI entrypoint for callers that want to execute or
resume a review loop without depending on command parsing or terminal command
modules.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import cast

from code_review_loop import budgets, reporting, resume, runner
from code_review_loop.clock import SYSTEM_CLOCK, Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import RunOutcome
from code_review_loop.core.ports import CommandResult, PhaseHarnessBundle, ProcessRunner
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity
from code_review_loop.runtime import RunLoopFailed, format_terminal_summary


@dataclass(frozen=True, init=False)
class ReviewLoopResult:
    """Typed application result with an explicit summary projection."""

    _summary: dict[str, object]
    outcome: RunOutcome

    def __init__(self, summary: dict[str, object], outcome: RunOutcome) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))
        object.__setattr__(self, "outcome", outcome)

    @property
    def summary(self) -> dict[str, object]:
        return copy.deepcopy(self._summary)

    def to_dict(self) -> dict[str, object]:
        return self.summary

    @property
    def final_status(self) -> str | None:
        value = self._summary.get("final_status")
        return value if isinstance(value, str) else None

    @property
    def stopped_reason(self) -> str | None:
        value = self._summary.get("stopped_reason")
        return value if isinstance(value, str) else None

    @property
    def artifact_dir(self) -> str | None:
        value = self._summary.get("artifact_dir")
        return value if isinstance(value, str) else None

    @property
    def run_id(self) -> str | None:
        value = self._summary.get("run_id")
        return value if isinstance(value, str) else None


def _load_default_process_runner() -> ProcessRunner:
    return cast(
        ProcessRunner, import_module("code_review_loop.adapters.subprocess_runner").default_runner
    )


def run_review_loop(
    config: LoopConfig,
    process_runner: ProcessRunner | None = None,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> ReviewLoopResult:
    """Run one bounded review/remediation loop and return the summary payload."""
    if process_runner is None:
        process_runner = _load_default_process_runner()
    # Headless callers opt out of all terminal progress emission, even if the
    # supplied config still has progress enabled for CLI runs.
    effective_config = replace(config, progress=False) if not terminal_ui else config
    result = runner.run_loop(
        effective_config,
        process_runner,
        clock=clock,
        identity=identity,
        budget_state=budget_state,
        phase_harnesses=phase_harnesses,
        terminal_ui=terminal_ui,
    )
    return ReviewLoopResult(summary=result.to_dict(), outcome=result.outcome)


def resume_review_loop(
    run_dir: Path,
    *,
    cwd: Path | None = None,
    process_runner: ProcessRunner | None = None,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> ReviewLoopResult:
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
    return run_review_loop(
        config,
        process_runner,
        clock=clock,
        identity=identity,
        budget_state=resumed_budget_state,
        phase_harnesses=phase_harnesses,
        terminal_ui=terminal_ui,
    )


def append_run_history(summary: dict[str, object], config: LoopConfig) -> Path:
    """Append the run summary to the operator's local run history."""
    return reporting.append_run_history(summary, config)


__all__ = [
    "CommandResult",
    "RunLoopFailed",
    "ReviewLoopResult",
    "append_run_history",
    "format_terminal_summary",
    "resume_review_loop",
    "run_review_loop",
]
