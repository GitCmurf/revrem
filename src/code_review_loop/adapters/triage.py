"""TriageHarness adapter body (REVREM-TASK-003 Wave C3a step 4).

Hosts ``run_triage`` and ``build_triage_command``, moved verbatim from
``code_review_loop.cli``. The contract-validation branches and adaptive-prompt
fallbacks are preserved; only the home module changes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from code_review_loop import (
    artifacts,
    diagnostics,
    harnesses,
    prompts_composer,
    suppressions,
    triage,
)
from code_review_loop.adapters import phase_support
from code_review_loop.core.ports import (
    CommandResult,
    RunContext,
    TriageOutcome,
    TriageRequest,
)
from code_review_loop.core.review_interpretation import actionable_review_output

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


def build_triage_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.triage_harness,
            role="triage",
            executable=phase_support._resolve_executable(config.triage_harness, config),
            model=config.triage_model,
            reasoning_effort=config.triage_reasoning_effort,
            sandbox="read-only",
            color=config.exec_color,
            full_auto=False,
        )
    )


def run_triage(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    run_id: str,
    source_review_artifact: str,
    review_output: str,
    ctx: RunContext,
) -> tuple[str, int, bool, dict[str, Any] | None]:
    command = build_triage_command(config)
    prompt_root = config.triage_prompt or triage.load_prompt(contract=config.triage_contract)
    prompt_root = _with_route_table(prompt_root, config)
    prompt = f"{prompt_root}\n{prompts_composer.trim_for_prompt(review_output, config.max_remediation_input_chars)}"
    prompt_artifact_path = config.artifact_dir / f"triage-{iteration}-prompt.txt"
    phase_support.write_artifact(prompt_artifact_path, prompt)
    invocation = harnesses.prepare_prompt_invocation(
        config.triage_harness,
        command,
        prompt,
        prompt_artifact_path=prompt_artifact_path,
    )
    command = invocation.command
    prompt_input = invocation.stdin
    prompt_metadata = phase_support.prompt_invocation_metadata(invocation)
    phase_support.ensure_model_budget(config, phase="triage", iteration=iteration, ctx=ctx)
    phase_support.progress_event(
        config,
        "triage",
        str(iteration),
        "start",
        phase_support.resolved_phase_detail(
            command,
            harness=config.triage_harness,
            model=config.triage_model,
            reasoning_effort=config.triage_reasoning_effort,
            timeout_seconds=config.triage_timeout_seconds_display,
            sandbox="read-only",
            contract=config.triage_contract,
            source=config.phase_config_sources.get("triage", "direct-config"),
            prompt_chars=prompt_metadata.get("prompt_chars"),
            prompt_delivery=prompt_metadata["prompt_delivery"],
        ),
        ctx=ctx,
        metadata={
            "command": phase_support.command_for_progress(list(command)),
            "harness": config.triage_harness,
            **prompt_metadata,
        },
    )
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN triage skipped\n")
    else:
        result = phase_support.run_with_waiting_progress(
            config,
            runner,
            command,
            config.cwd,
            prompt_input,
            phase_support.phase_timeout_seconds(config, config.triage_timeout_seconds),
            phase="triage",
            label=str(iteration),
            ctx=ctx,
            prompt_artifact=invocation.prompt_artifact,
        )
    triage_artifact = config.artifact_dir / f"triage-{iteration}.txt"
    phase_support.write_artifact(triage_artifact, phase_support._combined_output(result))
    phase_support.record_model_charge(config, result, phase="triage", iteration=iteration, ctx=ctx)
    if result.returncode != 0:
        issue = triage.command_failed_issue(
            iteration=iteration,
            returncode=result.returncode,
            artifact=str(triage_artifact),
        )
        artifacts.write_json_artifact(
            config.artifact_dir,
            f"diagnostics-{iteration}.json",
            diagnostics.doctor_payload([issue]),
        )
        phase_support.progress_event(
            config,
            "triage",
            str(iteration),
            "failed",
            f"exit {result.returncode}",
            ctx=ctx,
        )
        raise RuntimeError(
            f"codex exec triage failed for iteration {iteration}; see {triage_artifact}"
        )
    phase_support.progress_event(config, "triage", str(iteration), "done", ctx=ctx)
    triage_output = actionable_review_output(phase_support._combined_output(result))
    if triage.looks_structured_output(triage_output):
        try:
            payload = triage.parse_triage_payload(
                triage_output,
                run_id=run_id,
                source_review_artifact=source_review_artifact,
                contract=config.triage_contract,
            )
        except triage.TriageValidationError as exc:
            issue = triage.invalid_triage_issue(exc, iteration=iteration)
            artifacts.write_json_artifact(
                config.artifact_dir,
                f"diagnostics-{iteration}.json",
                diagnostics.doctor_payload([issue]),
            )
            phase_support.progress_event(
                config, "triage", str(iteration), "invalid", str(exc), ctx=ctx
            )
            if config.triage_on_invalid == "stop":
                raise RuntimeError(
                    f"invalid structured triage output for iteration {iteration}: {exc}"
                ) from exc
            return review_output, 0, False, None
        suppressed_count = 0
        if config.suppressions_enabled:
            try:
                matches = suppressions.load_effective_suppressions(config.cwd)
            except (OSError, ValueError) as exc:
                phase_support.progress_event(
                    config,
                    "triage",
                    str(iteration),
                    "warning",
                    f"suppressions unavailable; continuing without them: {exc}",
                    ctx=ctx,
                )
            else:
                payload, suppressed_findings = suppressions.apply_to_triage_payload(
                    payload, matches
                )
                suppressed_count = len(suppressed_findings)
                if suppressed_findings:
                    phase_support.progress_event(
                        config,
                        "triage",
                        str(iteration),
                        "suppressed",
                        f"{len(suppressed_findings)} finding(s)",
                        ctx=ctx,
                    )
        triage.write_triage_artifact(config.artifact_dir, iteration, payload)
        has_actionable_findings = bool(
            payload.get("confirmed_findings") or payload.get("needs_more_info")
        )
        if not has_actionable_findings:
            return "", suppressed_count, True, payload
        return (
            triage.format_structured_handoff(payload, review_output),
            suppressed_count,
            False,
            payload,
        )
    return (
        (
            "Triage handoff from the previous review:\n"
            f"{triage_output}\n\n"
            "Original review/check context:\n"
            f"{review_output}"
        ),
        0,
        False,
        None,
    )


class TriageAdapter:
    """Implements TriageHarness via the in-module ``run_triage`` body."""

    def __init__(self, config: LoopConfig) -> None:
        self._config = config

    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
        handoff, suppressed_count, is_clear, payload = run_triage(
            self._config,
            ctx.runner,
            request.iteration,
            request.run_id,
            request.source_review_artifact,
            request.review_output,
            ctx=ctx,
        )
        return TriageOutcome(
            handoff=handoff,
            suppressed_count=suppressed_count,
            is_clear=is_clear,
            payload=payload,
        )


def _with_route_table(prompt_root: str, config: LoopConfig) -> str:
    if config.triage_contract != "v2" or config.profile_v2 is None:
        return prompt_root
    routing = config.profile_v2.triage.routing
    routes = config.profile_v2.triage.routes
    if not routing.enabled or not routes:
        return prompt_root
    lines = [
        "Configured remediation routes for route_proposal.route_tier:",
        f"- default route: {routing.default_route}",
    ]
    for name, route in sorted(routes.items()):
        parts = [f"- {name}: harness={route.harness}"]
        if route.model:
            parts.append(f"model={route.model}")
        if route.reasoning_effort:
            parts.append(f"effort={route.reasoning_effort}")
        parts.append("timeout=" + _route_timeout_text(route.timeout_seconds))
        parts.append(f"sandbox={route.sandbox}")
        if route.fallback:
            parts.append(f"fallback={route.fallback}")
        lines.append(", ".join(parts))
    lines.append(
        "Use one of these exact route names when proposing a route. "
        "RevRem policy may still override or fall back from the proposal. "
        "When a route shows timeout=none, emit route_proposal.timeout_seconds as 0."
    )
    return f"{prompt_root}\n\n" + "\n".join(lines)


def _route_timeout_text(value: float | None) -> str:
    if value is None:
        return "profile/default"
    if value == 0:
        return "none"
    return f"{value:g}s"
