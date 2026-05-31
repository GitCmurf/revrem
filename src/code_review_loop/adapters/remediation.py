"""RemediationHarness adapter body (REVREM-TASK-003 Wave C3a step 3).

Hosts ``run_remediation`` and ``build_remediation_command``, moved verbatim
from ``code_review_loop.cli``. Loop-shell helpers stay in cli for now and are
reached through the module-level ``phase_support`` alias; C3 cleanup retires it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from code_review_loop import (
    harnesses,
    policy,
    prompts_composer,
)
from code_review_loop.adapters import phase_support
from code_review_loop.core.ports import (
    CommandResult,
    RemediationOutcome,
    RemediationRequest,
    RunContext,
)

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


def build_remediation_command(
    config: LoopConfig,
    output_last_message: Path | None = None,
    resolved_route: policy.ResolvedRoute | None = None,
) -> list[str]:
    harness = resolved_route.harness if resolved_route else config.remediation_harness
    model = (
        (resolved_route.model if resolved_route else None)
        or config.remediation_model
        or config.model
    )
    reasoning_effort = (
        (resolved_route.reasoning_effort if resolved_route else None)
        or config.remediation_reasoning_effort
        or config.reasoning_effort
    )
    sandbox = resolved_route.sandbox if resolved_route else config.exec_sandbox

    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=harness,
            role="remediation",
            executable=phase_support._resolve_executable(harness, config),
            model=model,
            reasoning_effort=reasoning_effort,
            sandbox=sandbox,
            color=config.exec_color,
            full_auto=config.full_auto,
            json_output=config.exec_json,
            output_last_message_path=output_last_message,
        )
    )


def run_remediation(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    remediation_input: str,
    *,
    resolved_route: policy.ResolvedRoute | None = None,
    ctx: RunContext,
) -> CommandResult:
    last_message_path = (
        config.artifact_dir / f"remediation-{iteration}-last-message.txt"
        if config.output_last_message
        else None
    )
    command = build_remediation_command(config, last_message_path, resolved_route=resolved_route)
    remediation_harness = (
        resolved_route.harness if resolved_route else config.remediation_harness
    )

    if resolved_route:
        prompt = remediation_input
        timeout = resolved_route.timeout_seconds
    else:
        prompt = f"{phase_support.DEFAULT_REMEDIATION_PROMPT}\n{prompts_composer.trim_for_prompt(remediation_input, config.max_remediation_input_chars)}"
        timeout = config.remediation_timeout_seconds
    command, prompt_input = harnesses.prepare_prompt_invocation(
        remediation_harness,
        command,
        prompt,
    )

    phase_support.set_phase_terminal_title(config, "remediate", str(iteration))
    phase_support.ensure_model_budget(config, phase="remediate", iteration=iteration, ctx=ctx)
    phase_support.progress_event(
        config,
        "remediate",
        str(iteration),
        "start",
        phase_support.resolved_phase_detail(
            command,
            harness=remediation_harness,
            model=(resolved_route.model if resolved_route else None)
            or config.remediation_model
            or config.model,
            reasoning_effort=(resolved_route.reasoning_effort if resolved_route else None)
            or config.remediation_reasoning_effort
            or config.reasoning_effort,
            timeout_seconds=(
                resolved_route.timeout_seconds
                if resolved_route
                else config.remediation_timeout_seconds_display
            ),
            sandbox=(resolved_route.sandbox if resolved_route else config.exec_sandbox),
            source=(
                f"route:{resolved_route.route_tier}"
                if resolved_route
                else config.phase_config_sources.get("remediation", "direct-config")
            ),
        ),
        ctx=ctx,
    )
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN remediation skipped\n")
    else:
        result = runner(command, config.cwd, prompt_input, phase_support.phase_timeout_seconds(config, timeout))
    phase_support.write_artifact(config.artifact_dir / f"remediation-{iteration}.txt", phase_support._combined_output(result))
    phase_support.record_model_charge(config, result, phase="remediate", iteration=iteration, ctx=ctx)
    if result.returncode != 0:
        phase_support.progress_event(config, "remediate", str(iteration), "failed", f"exit {result.returncode}", ctx=ctx)
        raise RuntimeError(
            f"codex exec remediation failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'remediation-{iteration}.txt'}"
        )
    phase_support.progress_event(config, "remediate", str(iteration), "done", ctx=ctx)
    return result


class RemediationAdapter:
    """Implements RemediationHarness via the in-module ``run_remediation`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        result = run_remediation(
            self._config,
            ctx.runner,
            request.iteration,
            request.remediation_input,
            resolved_route=request.resolved_route,
            ctx=ctx,
        )
        return RemediationOutcome(result=result)
