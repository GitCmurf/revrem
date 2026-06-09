"""Read-only stale-review validation adapter helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from code_review_loop import harnesses, provider_failures, stale_review
from code_review_loop.adapters import phase_support
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RunContext

StaleValidationStatus = Literal["resolved", "still_applies", "unknown"]


@dataclass(frozen=True)
class StaleValidationOutcome:
    status: StaleValidationStatus
    result: CommandResult
    summary: str


def run_stale_validation(
    config: LoopConfig,
    ctx: RunContext,
    *,
    iteration: int,
    validation_input: str,
) -> StaleValidationOutcome:
    label = f"stale-validation-{iteration}"
    prompt = stale_review.read_only_validation_prompt(validation_input)
    prompt_artifact = config.artifact_dir / f"{label}-prompt.txt"
    phase_support.write_artifact(prompt_artifact, prompt)
    command = _build_validation_command(config)
    invocation = harnesses.prepare_prompt_invocation(
        config.review_harness,
        command,
        prompt,
        prompt_artifact_path=prompt_artifact,
    )
    metadata = phase_support.prompt_invocation_metadata(invocation)
    phase_support.progress_event(
        config,
        "stale-validation",
        str(iteration),
        "start",
        phase_support.resolved_phase_detail(
            invocation.command,
            harness=config.review_harness,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
            timeout_seconds=config.review_timeout_seconds_display,
            sandbox="read-only",
            source=config.phase_config_sources.get("review", "direct-config"),
            prompt_chars=metadata.get("prompt_chars"),
            prompt_delivery=metadata["prompt_delivery"],
        ),
        ctx=ctx,
        metadata={
            "command": phase_support.command_for_progress(list(invocation.command)),
            "harness": config.review_harness,
            **metadata,
        },
    )
    import time

    from code_review_loop.adapters.review import review_failed_to_run

    attempts = (
        config.provider_retry_attempts if config.review_harness not in {"codex", "fake"} else 1
    )
    last_result = None
    for attempt in range(1, attempts + 1):
        result = phase_support.run_with_waiting_progress(
            config,
            ctx.runner,
            invocation.command,
            config.cwd,
            invocation.stdin,
            phase_support.phase_timeout_seconds(config, config.review_timeout_seconds),
            phase="stale-validation",
            label=str(iteration),
            ctx=ctx,
            prompt_artifact=invocation.prompt_artifact,
        )
        last_result = result
        failure = provider_failures.classify_provider_failure(result, harness=config.review_harness)
        if (
            not review_failed_to_run(result, config.review_harness)
            or failure is None
            or not failure.transient
        ):
            break
        phase_support.write_artifact(
            config.artifact_dir / f"stale-validation-{iteration}-attempt-{attempt}.txt",
            phase_support._combined_output(result),
        )
        if attempt < attempts:
            phase_support.progress_event(
                config,
                "stale-validation",
                str(iteration),
                "retry",
                failure.detail,
                ctx=ctx,
                metadata={"reason": failure.reason, "attempt": attempt},
            )
            time.sleep(config.provider_retry_backoff_seconds)
    assert last_result is not None
    result = last_result
    combined = phase_support._combined_output(result)
    artifact_path = config.artifact_dir / f"{label}.txt"
    phase_support.write_artifact(artifact_path, combined)
    phase_support.record_model_charge(
        config, result, phase="stale-validation", iteration=str(iteration), ctx=ctx
    )
    status = cast(StaleValidationStatus, stale_review.validation_status(combined))
    if result.returncode != 0:
        failure = provider_failures.classify_provider_failure(result, harness=config.review_harness)
        failure_detail = f": {failure.detail}" if failure else ""
        phase_support.progress_event(
            config,
            "stale-validation",
            str(iteration),
            "failed",
            f"exit {result.returncode}{failure_detail}",
            ctx=ctx,
        )
        raise RuntimeError(
            f"{config.review_harness} stale validation failed for iteration {iteration}; "
            f"see {artifact_path}{failure_detail}"
        )
    if status == "unknown":
        phase_support.progress_event(
            config,
            "stale-validation",
            str(iteration),
            "unknown",
            "missing or unknown stale-review status",
            ctx=ctx,
        )
        raise RuntimeError(f"stale review validation returned unknown status; see {artifact_path}")
    phase_support.progress_event(
        config,
        "stale-validation",
        str(iteration),
        status,
        ctx=ctx,
    )
    return StaleValidationOutcome(
        status=status,
        result=result,
        summary=stale_review.validation_summary(combined),
    )


def _build_validation_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.review_harness,
            role="triage",
            executable=phase_support._resolve_executable(config.review_harness, config),
            base=config.base,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
            sandbox="read-only",
            full_auto=False,
        )
    )
