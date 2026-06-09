"""Acceptance traces for the dependency-free core engine runner."""

from __future__ import annotations

from dataclasses import replace

from code_review_loop.core.engine import (
    Action,
    ChecksDone,
    CommitDone,
    ConfigSnapshot,
    EngineState,
    LoopAccumulator,
    LoopStarted,
    NoFinalReview,
    PhaseEvent,
    RemediationDone,
    RetryViaCommitHook,
    ReviewDone,
    RunChecks,
    RunCommit,
    RunRemediation,
    RunReview,
    RunTriage,
    TriageDone,
    run,
)
from code_review_loop.core.outcome import OutcomeClear, OutcomeFailed, OutcomeUnknown


def _cfg(
    *,
    max_iterations: int = 2,
    triage_enabled: bool = False,
    commit_after_remediation: bool = False,
    commit_on_hook_failure: str = "fail",
    final_review: bool = True,
) -> ConfigSnapshot:
    return ConfigSnapshot(
        max_iterations=max_iterations,
        triage_enabled=triage_enabled,
        commit_after_remediation=commit_after_remediation,
        commit_on_hook_failure=commit_on_hook_failure,
        final_review=final_review,
    )


class _HookFailed(Exception):
    kind = "hook_failed"


class RecordingEngineExecutor:
    def __init__(self, events: list[object]) -> None:
        self.events = list(events)
        self.actions: list[Action] = []

    def execute(self, action: Action, state: EngineState) -> EngineState:
        self.actions.append(action)
        if isinstance(action, RetryViaCommitHook):
            return replace(
                state,
                acc=replace(
                    state.acc,
                    commit_retry=True,
                    pending_check_failures=action.hook_output,
                ),
                event=LoopStarted(),
                iteration=state.iteration + 1,
            )
        if isinstance(action, RunReview):
            event = self._next_event()
            return replace(state, event=event)
        if isinstance(action, RunTriage):
            event = self._next_event()
            return replace(state, event=event)
        if isinstance(action, RunRemediation):
            return replace(state, event=RemediationDone())
        if isinstance(action, RunChecks):
            return replace(
                state,
                acc=replace(state.acc, pending_check_failures=""),
                event=ChecksDone(),
            )
        if isinstance(action, RunCommit):
            event = self._next_event()
            return replace(state, event=event)
        return replace(state, event=LoopStarted(), iteration=state.iteration + 1)

    def _next_event(self) -> PhaseEvent:
        event = self.events.pop(0)
        if isinstance(
            event,
            (
                LoopStarted,
                ReviewDone,
                TriageDone,
                RemediationDone,
                ChecksDone,
                CommitDone,
                NoFinalReview,
            ),
        ):
            return event
        raise AssertionError(f"unexpected event: {event!r}")


def _start(cfg: ConfigSnapshot) -> EngineState:
    return EngineState(
        cfg=cfg,
        acc=LoopAccumulator(pending_check_failures=""),
        event=LoopStarted(),
        iteration=1,
    )


def test_run_trace_review_clear_terminal_path() -> None:
    executor = RecordingEngineExecutor([ReviewDone(is_final=False, status="clear")])

    outcome = run(_start(_cfg()), executor)

    assert isinstance(outcome, OutcomeClear)
    assert outcome.reason == "review_clear"
    assert executor.actions == [RunReview(is_final=False)]


def test_run_trace_findings_triage_remediation_checks_final_clear() -> None:
    executor = RecordingEngineExecutor(
        [
            ReviewDone(is_final=False, status="findings"),
            TriageDone(is_clear=False),
            ReviewDone(is_final=True, status="clear"),
        ]
    )

    outcome = run(_start(_cfg(max_iterations=1, triage_enabled=True)), executor)

    assert isinstance(outcome, OutcomeClear)
    assert outcome.reason == "review_clear"
    assert executor.actions == [
        RunReview(is_final=False),
        RunTriage(),
        RunRemediation(),
        RunChecks(),
        RunReview(is_final=True),
    ]


def test_run_trace_commit_hook_retry() -> None:
    executor = RecordingEngineExecutor(
        [
            ReviewDone(is_final=False, status="findings"),
            CommitDone(status=None, commit_failed=_HookFailed("hook failed")),
            ReviewDone(is_final=False, status="clear"),
            CommitDone(status="committed"),
            ReviewDone(is_final=True, status="clear"),
        ]
    )

    outcome = run(
        _start(
            _cfg(
                max_iterations=2,
                commit_after_remediation=True,
                commit_on_hook_failure="remediate",
            )
        ),
        executor,
    )

    assert isinstance(outcome, OutcomeClear)
    assert [type(action) for action in executor.actions] == [
        RunReview,
        RunRemediation,
        RunChecks,
        RunCommit,
        RetryViaCommitHook,
        RunReview,
        RunRemediation,
        RunChecks,
        RunCommit,
        RunReview,
    ]


def test_run_trace_no_final_review_exhaustion() -> None:
    state = EngineState(
        cfg=_cfg(max_iterations=1, final_review=False),
        acc=LoopAccumulator(pending_check_failures=""),
        event=NoFinalReview(),
        iteration=1,
    )
    executor = RecordingEngineExecutor([])

    outcome = run(state, executor)

    assert isinstance(outcome, OutcomeUnknown)
    assert outcome.reason == "max_iterations_reached"
    assert executor.actions == []


def test_run_step_limit_fails_closed_when_executor_never_reaches_terminal() -> None:
    state = EngineState(
        cfg=_cfg(),
        acc=LoopAccumulator(pending_check_failures=""),
        event=RemediationDone(),
    )
    executor = RecordingEngineExecutor([])

    outcome = run(state, executor, max_steps=0)

    assert isinstance(outcome, OutcomeFailed)
    assert outcome.reason == "engine_step_limit_exceeded"
