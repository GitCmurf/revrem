"""Tests for the dependency-free core engine runner."""

from __future__ import annotations

from dataclasses import replace

from code_review_loop.core.engine import (
    Action,
    ConfigSnapshot,
    EngineState,
    LoopAccumulator,
    RemediationDone,
    ReviewDone,
    RunChecks,
    run,
)
from code_review_loop.core.outcome import OutcomeClear, OutcomeFailed


def _cfg() -> ConfigSnapshot:
    return ConfigSnapshot(
        max_iterations=2,
        triage_enabled=False,
        commit_after_remediation=False,
        commit_on_hook_failure="fail",
        final_review=True,
    )


class RecordingExecutor:
    def __init__(self, next_state: EngineState) -> None:
        self.next_state = next_state
        self.actions: list[Action] = []

    def execute(self, action: Action, state: EngineState) -> EngineState:
        self.actions.append(action)
        return self.next_state


def test_run_returns_terminal_outcome_without_executor_side_effects() -> None:
    state = EngineState(
        cfg=_cfg(),
        acc=LoopAccumulator(pending_check_failures=""),
        event=ReviewDone(is_final=False, status="clear"),
    )
    executor = RecordingExecutor(state)

    outcome = run(state, executor)

    assert isinstance(outcome, OutcomeClear)
    assert outcome.reason == "review_clear"
    assert executor.actions == []


def test_run_delegates_continue_to_executor_until_terminal() -> None:
    initial = EngineState(
        cfg=_cfg(),
        acc=LoopAccumulator(pending_check_failures=""),
        event=RemediationDone(),
        iteration=1,
    )
    terminal = replace(initial, event=ReviewDone(is_final=False, status="clear"))
    executor = RecordingExecutor(terminal)

    outcome = run(initial, executor)

    assert isinstance(outcome, OutcomeClear)
    assert len(executor.actions) == 1
    assert isinstance(executor.actions[0], RunChecks)


def test_run_step_limit_fails_closed_when_executor_never_reaches_terminal() -> None:
    state = EngineState(
        cfg=_cfg(),
        acc=LoopAccumulator(pending_check_failures=""),
        event=RemediationDone(),
    )
    executor = RecordingExecutor(state)

    outcome = run(state, executor, max_steps=0)

    assert isinstance(outcome, OutcomeFailed)
    assert outcome.reason == "engine_step_limit_exceeded"
