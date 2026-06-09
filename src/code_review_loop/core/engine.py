"""Dependency-free review/remediation engine decisions (REVREM-TASK-003).

Design
------
``decide(cfg, acc, event)`` is a total, side-effect-free function. It receives
a read-only slice of config (``ConfigSnapshot``), accumulated loop state
(``LoopAccumulator``), and the result of the most-recently-completed phase
(``PhaseEvent``). It returns one ``Action`` variant. ``run(state, executor)``
applies those actions through an injected imperative executor, so the core
remains independent of CLI, terminal, subprocess, and artifact concerns.

All types are frozen dataclasses so that value tests can construct them
inline without mocking.

Row references (G1, P1, R1 …) map 1:1 to the branch→transition→outcome table
committed to docs/05-planning/behaviour-ledger-task-003.md (B3a gate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, assert_never

from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFailedReason,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)
from code_review_loop.core.routing_types import ResolvedRoute

# ---------------------------------------------------------------------------
# Config snapshot (read-only slice the engine needs from LoopConfig)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigSnapshot:
    """Immutable slice of LoopConfig relevant to the engine's decisions."""

    max_iterations: int
    triage_enabled: bool
    commit_after_remediation: bool
    commit_on_hook_failure: str  # "fail" | "remediate" | "no-verify"
    final_review: bool
    inner_check_retries: int = 0


# ---------------------------------------------------------------------------
# Loop accumulator (mutable across iterations; passed by value each call)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopAccumulator:
    """Loop state accumulated across iterations."""

    pending_check_failures: str  # empty string means none
    commit_retry: bool = False
    last_review_status: Literal["clear", "findings", "unknown"] = "unknown"
    last_review_output: str = ""
    remediation_input: str = ""
    resolved_route: ResolvedRoute | None = None
    failed_check_names: tuple[str, ...] = ()
    remediation_result_returncode: int | None = None
    remediation_duration: float = 0.0
    inner_check_retry_count: int = 0
    stale_review_resolved: bool = False
    stale_review_dirty: str = ""


# ---------------------------------------------------------------------------
# Phase events — one variant per phase, carrying its result and any exception
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewDone:
    """Emitted after a review subprocess completes (iteration or final)."""

    is_final: bool
    status: Literal["clear", "findings", "unknown"]
    exc: BaseException | None = None


@dataclass(frozen=True)
class LoopStarted:
    """Emitted to request the first review of an iteration."""


@dataclass(frozen=True)
class TriageDone:
    """Emitted after the triage phase completes."""

    is_clear: bool  # triage found no actionable findings
    suppressed_count: int = 0
    exc: BaseException | None = None


@dataclass(frozen=True)
class RemediationDone:
    """Emitted after the remediation phase completes."""

    exc: BaseException | None = None
    failure_reason: OutcomeFailedReason = "remediation_failed"


@dataclass(frozen=True)
class ChecksDone:
    """Emitted after verification checks complete."""


@dataclass(frozen=True)
class CommitDone:
    """Emitted after the commit phase completes (or is skipped)."""

    status: str | None  # "committed" | "skipped" | "skipped_no_changes"
    commit_failed: BaseException | None = None  # CommitFailed instance
    other_exc: BaseException | None = None


@dataclass(frozen=True)
class NoFinalReview:
    """Emitted post-loop when config.final_review is False."""


PhaseEvent = (
    LoopStarted
    | ReviewDone
    | TriageDone
    | RemediationDone
    | ChecksDone
    | CommitDone
    | NoFinalReview
)


# ---------------------------------------------------------------------------
# Action ADT — every variant corresponds to a compound transition + outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Continue:
    """Loop advances to the next phase / iteration (L1, L2, L3, M1, CK1)."""


@dataclass(frozen=True)
class RunReview:
    """Run an iteration or final review."""

    is_final: bool = False


@dataclass(frozen=True)
class RunTriage:
    """Run the triage phase for current review findings."""


@dataclass(frozen=True)
class RunRemediation:
    """Run the remediation phase."""


@dataclass(frozen=True)
class RunChecks:
    """Run verification checks after remediation."""


@dataclass(frozen=True)
class RunCommit:
    """Run the optional commit phase."""


@dataclass(frozen=True)
class RetryViaCommitHook:
    """Commit hook failed retryably; feed output into next iteration (CM3, L4)."""

    hook_output: str


@dataclass(frozen=True)
class RetryViaChecks:
    """Verification failed; feed check output into a bounded remediation retry."""


@dataclass(frozen=True)
class Stop:
    """Loop exits; outcome carries the terminal state (E1, T2, T3, F2-F6, NF1, …)."""

    outcome: RunOutcome


Action = (
    Continue
    | RunReview
    | RunTriage
    | RunRemediation
    | RunChecks
    | RunCommit
    | RetryViaCommitHook
    | RetryViaChecks
    | Stop
)


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineState:
    """Dependency-free engine state consumed by :func:`run`.

    The shell owns all I/O. The core only decides the next ``Action`` for the
    latest ``event`` and asks the injected executor to produce the next state
    after non-terminal actions.
    """

    cfg: ConfigSnapshot
    acc: LoopAccumulator
    event: PhaseEvent
    iteration: int = 1


class EngineExecutor(Protocol):
    """Imperative shell callback used by :func:`run` for non-terminal actions."""

    def execute(self, action: Action, state: EngineState) -> EngineState:
        """Apply one non-terminal action and return the next engine state."""
        ...


def run(state: EngineState, ctx: EngineExecutor, *, max_steps: int | None = None) -> RunOutcome:
    """Drive the dependency-free engine until it reaches a terminal outcome.

    ``run`` is intentionally small: every pure branch decision remains in
    ``decide``; every side effect stays behind ``ctx.execute``. A non-CLI caller
    can therefore drive the same core by providing an executor that translates
    actions into the next phase event.
    """

    steps = 0
    while True:
        action = decide(state.cfg, state.acc, state.event, iteration=state.iteration)
        if isinstance(action, Stop):
            return action.outcome
        if max_steps is not None and steps >= max_steps:
            return OutcomeFailed(
                reason="engine_step_limit_exceeded", error="engine step limit exceeded"
            )
        if isinstance(
            action,
            (
                Continue,
                RunReview,
                RunTriage,
                RunRemediation,
                RunChecks,
                RunCommit,
                RetryViaCommitHook,
                RetryViaChecks,
            ),
        ):
            state = ctx.execute(action, state)
            steps += 1
            continue
        assert_never(action)


# ---------------------------------------------------------------------------
# Pure decision function
# ---------------------------------------------------------------------------


def decide(
    cfg: ConfigSnapshot, acc: LoopAccumulator, event: PhaseEvent, *, iteration: int = 1
) -> Action:
    """Return the Action the shell should apply for the given phase event.

    This function is pure: no I/O, no side effects, deterministic. The
    application executor is responsible for translating non-terminal actions
    into the next phase event.
    """
    if isinstance(event, LoopStarted):
        return RunReview(is_final=False)
    if isinstance(event, ReviewDone):
        return _decide_review(cfg, acc, event)
    if isinstance(event, TriageDone):
        return _decide_triage(acc, event)
    if isinstance(event, RemediationDone):
        return _decide_remediation(event)
    if isinstance(event, ChecksDone):
        return _decide_checks(cfg, acc, iteration)
    if isinstance(event, CommitDone):
        return _decide_commit(cfg, acc, event, iteration)
    if isinstance(event, NoFinalReview):  # NF1
        return _decide_no_final_review(acc)

    assert_never(event)


def _decide_review(cfg: ConfigSnapshot, acc: LoopAccumulator, event: ReviewDone) -> Action:
    if event.exc is not None:
        return Stop(OutcomeFailed(reason="review_failed", error=str(event.exc)))
    if not event.is_final:
        if event.status == "clear" and not acc.pending_check_failures:
            return Stop(OutcomeClear(reason="review_clear", excerpt=""))
        if event.status == "unknown" and not acc.pending_check_failures:
            return Stop(OutcomeUnknown(reason="review_unknown"))
        if cfg.triage_enabled:
            return RunTriage()
        return RunRemediation()
    if acc.pending_check_failures:
        return Stop(
            OutcomeFindings(
                reason="max_iterations_reached_with_check_failures",
                check_failures=True,
            )
        )
    if event.status == "clear":
        return Stop(OutcomeClear(reason="review_clear"))
    if event.status == "findings":
        return Stop(OutcomeFindings(reason="max_iterations_reached"))
    return Stop(OutcomeUnknown(reason="max_iterations_reached"))


def _decide_triage(acc: LoopAccumulator, event: TriageDone) -> Action:
    if event.exc is not None:
        return Stop(OutcomeFailed(reason="triage_failed", error=str(event.exc)))
    if event.is_clear and not acc.pending_check_failures:
        if event.suppressed_count:
            return Stop(
                OutcomeClear(
                    reason="all_findings_suppressed",
                    suppressed_findings_count=event.suppressed_count,
                )
            )
        return Stop(OutcomeClear(reason="triage_rejected_all_findings"))
    return RunRemediation()


def _decide_remediation(event: RemediationDone) -> Action:
    if event.exc is not None:
        return Stop(OutcomeFailed(reason=event.failure_reason, error=str(event.exc)))
    return RunChecks()


def _decide_checks(cfg: ConfigSnapshot, acc: LoopAccumulator, iteration: int) -> Action:
    if acc.stale_review_resolved:
        if acc.stale_review_dirty:
            return Stop(
                OutcomeFailed(
                    reason="stale_validation_failed",
                    error=acc.stale_review_dirty,
                )
            )
        if acc.pending_check_failures:
            return Stop(
                OutcomeFailed(
                    reason="stale_validation_failed",
                    error=(
                        "stale review validation emitted resolved marker but "
                        "verification checks failed"
                    ),
                    check_failures=True,
                )
            )
        return Stop(OutcomeClear(reason="stale_review_already_resolved"))
    if cfg.commit_after_remediation and not acc.pending_check_failures:
        return RunCommit()
    if acc.pending_check_failures and acc.inner_check_retry_count < cfg.inner_check_retries:
        return RetryViaChecks()
    return _next_review_action(cfg, acc, iteration)


def _decide_commit(
    cfg: ConfigSnapshot, acc: LoopAccumulator, event: CommitDone, iteration: int
) -> Action:
    if event.other_exc is not None:
        return Stop(OutcomeFailed(reason="commit_failed", error=str(event.other_exc)))
    if event.commit_failed is not None:
        kind = getattr(event.commit_failed, "kind", "")
        retryable = (
            kind == "hook_failed"
            and cfg.commit_on_hook_failure in ("remediate", "no-verify")
            and iteration < cfg.max_iterations
        )
        if retryable:
            return RetryViaCommitHook(hook_output=str(event.commit_failed))
        if kind == "hook_failed":
            return Stop(
                OutcomeFailed(
                    reason="commit_hook_failed",
                    error=str(event.commit_failed),
                    staged_changes_left=True,
                    check_failures=True,
                )
            )
        return Stop(OutcomeFailed(reason="commit_failed", error=str(event.commit_failed)))
    if event.status == "skipped_no_changes":
        if acc.stale_review_resolved:
            return Stop(OutcomeClear(reason="stale_review_already_resolved"))
        if acc.last_review_status == "clear":
            return Stop(OutcomeClear(reason="no_changes_after_remediation"))
        if acc.last_review_status == "unknown":
            return Stop(OutcomeUnknown(reason="no_changes_after_remediation"))
        if acc.last_review_status == "findings":
            return Stop(OutcomeFindings(reason="no_changes_after_remediation"))
    if acc.stale_review_resolved and event.status == "committed":
        return Stop(
            OutcomeFailed(
                reason="stale_validation_failed",
                error=(
                    "stale review validation emitted resolved marker but produced changes to commit"
                ),
            )
        )
    return _next_review_action(cfg, acc, iteration)


def _decide_no_final_review(acc: LoopAccumulator) -> Action:
    return Stop(
        OutcomeUnknown(
            reason="max_iterations_reached",
            check_failures=bool(acc.pending_check_failures),
        )
    )


def _next_review_action(cfg: ConfigSnapshot, acc: LoopAccumulator, iteration: int) -> Action:
    if iteration < cfg.max_iterations:
        return Continue()
    if cfg.final_review:
        return RunReview(is_final=True)
    return _decide_no_final_review(acc)
