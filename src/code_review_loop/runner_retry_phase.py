"""Retry transition helpers for the runner shell."""

from __future__ import annotations

from dataclasses import replace

from code_review_loop.adapters.commit import format_commit_hook_failure_for_remediation
from code_review_loop.adapters.phase_support import CommitFailed, progress_event
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import (
    CommitDone,
    EngineState,
    LoopStarted,
    RetryViaCommitHook,
)
from code_review_loop.core.ports import RunContext
from code_review_loop.core.state import RunState


def retry_after_checks(config: LoopConfig, ctx: RunContext, engine_state: EngineState) -> EngineState:
    retry_count = engine_state.acc.inner_check_retry_count + 1
    progress_event(
        config,
        "check",
        str(engine_state.iteration),
        "retry",
        f"check failures will feed remediation retry {retry_count}/{config.inner_check_retries}",
        ctx=ctx,
    )
    acc = replace(
        engine_state.acc,
        inner_check_retry_count=retry_count,
        remediation_input=engine_state.acc.pending_check_failures + "\n\n" + engine_state.acc.remediation_input,
    )
    return replace(engine_state, acc=acc)


def retry_after_commit_hook(
    *,
    config: LoopConfig,
    ctx: RunContext,
    state: RunState,
    engine_state: EngineState,
    action: RetryViaCommitHook,
) -> EngineState:
    commit_failed = engine_state.event.commit_failed if isinstance(engine_state.event, CommitDone) else None
    if not isinstance(commit_failed, CommitFailed):
        raise RuntimeError(action.hook_output)
    pending_check_failures = format_commit_hook_failure_for_remediation(commit_failed)
    state.set_pending_check_failures(True)
    progress_event(
        config,
        "commit",
        str(engine_state.iteration),
        "retry",
        "hook output will feed next remediation",
        ctx=ctx,
    )
    acc = replace(engine_state.acc, commit_retry=True, pending_check_failures=pending_check_failures)
    return replace(engine_state, acc=acc, event=LoopStarted(), iteration=engine_state.iteration + 1)
