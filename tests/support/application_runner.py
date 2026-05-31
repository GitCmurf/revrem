"""Test shim for the supported application execution boundary."""

from __future__ import annotations

from pathlib import Path

from code_review_loop import application, budgets
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import PhaseHarnessBundle, ProcessRunner
from code_review_loop.identity import RunIdentity


def run_loop(
    config: LoopConfig,
    runner: ProcessRunner,
    *,
    clock: Clock | None = None,
    identity: RunIdentity | None = None,
    budget_state: budgets.BudgetState | None = None,
    phase_harnesses: PhaseHarnessBundle | None = None,
    terminal_ui: bool = True,
) -> application.ReviewLoopResult:
    kwargs = {
        "budget_state": budget_state,
        "phase_harnesses": phase_harnesses,
        "terminal_ui": terminal_ui,
    }
    if clock is not None:
        kwargs["clock"] = clock
    if identity is not None:
        kwargs["identity"] = identity
    return application.run_review_loop(config, runner, **kwargs)


def resume_run(run_dir: Path, runner: ProcessRunner) -> application.ReviewLoopResult:
    return application.resume_review_loop(run_dir, process_runner=runner)
