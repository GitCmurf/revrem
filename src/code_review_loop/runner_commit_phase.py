"""Commit-phase execution helper for the runner shell."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from code_review_loop import budgets
from code_review_loop.adapters.phase_support import CommitFailed, emit_loop_failure_event
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import CommitDone, EngineState
from code_review_loop.core.ports import CommitRequest, RunContext
from code_review_loop.run_guards import current_head


@dataclass(frozen=True)
class CommitPhaseResult:
    state: EngineState
    cause: BaseException | None
    expected_head: str | None


def execute_commit_phase(
    *,
    config: LoopConfig,
    ctx: RunContext,
    iterations: list[dict[str, object]],
    engine_state: EngineState,
    expected_head: str | None,
) -> CommitPhaseResult:
    iteration = engine_state.iteration
    try:
        commit_outcome = ctx.phase_commit.execute(
            CommitRequest(iteration=iteration, retrying=engine_state.acc.commit_retry),
            ctx,
        )
        iterations[-1]["commit_status"] = commit_outcome.status
        if commit_outcome.status == "committed" and (config.cwd / ".git").exists():
            expected_head = current_head(config, ctx) or expected_head
    except CommitFailed as exc:
        iterations[-1]["commit_status"] = exc.kind
        iterations[-1]["commit_failed"] = True
        iterations[-1]["commit_artifact"] = str(exc.artifact_path)
        return CommitPhaseResult(
            replace(engine_state, event=CommitDone(status=exc.kind, commit_failed=exc)),
            exc,
            expected_head,
        )
    except budgets.BudgetExceeded:
        raise
    except Exception as exc:
        iterations[-1]["commit_failed"] = True
        emit_loop_failure_event(
            config,
            phase="commit",
            iteration=iteration,
            reason="commit_failed",
            error=str(exc),
            ctx=ctx,
        )
        return CommitPhaseResult(
            replace(engine_state, event=CommitDone(status=None, other_exc=exc)),
            exc,
            expected_head,
        )
    return CommitPhaseResult(
        replace(
            engine_state,
            event=CommitDone(status=cast("str | None", iterations[-1].get("commit_status"))),
        ),
        None,
        expected_head,
    )
