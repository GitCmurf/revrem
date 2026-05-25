"""TriageHarness adapter body (REVREM-TASK-003 Wave C3a step 4).

Hosts ``run_triage`` and ``build_triage_command``, moved verbatim from
``code_review_loop.cli``. The contract-validation branches and adaptive-prompt
fallbacks are preserved; only the home module changes.
"""

from __future__ import annotations

import shlex
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
from code_review_loop import loop as _cli  # noqa: E402  -- loop-shell helpers
from code_review_loop.core.ports import CommandResult, RunContext
from code_review_loop.core.review_interpretation import actionable_review_output

if TYPE_CHECKING:
    from code_review_loop.config import LoopConfig

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


def build_triage_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.triage_harness,
            role="triage",
            executable=_cli._resolve_executable(config.triage_harness, config),
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
    ctx: RunContext | None = None,
) -> tuple[str, int, bool, dict[str, Any] | None]:
    command = build_triage_command(config)
    prompt_root = config.triage_prompt or triage.load_prompt(contract=config.triage_contract)
    prompt = f"{prompt_root}\n{prompts_composer.trim_for_prompt(review_output, config.max_remediation_input_chars)}"
    command, prompt_input = harnesses.prepare_prompt_invocation(
        config.triage_harness,
        command,
        prompt,
    )
    _cli.ensure_model_budget(config, phase="triage", iteration=iteration, ctx=ctx)
    _cli.progress_event(config, "triage", str(iteration), "start", shlex.join(command), ctx=ctx)
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN triage skipped\n")
    else:
        result = runner(command, config.cwd, prompt_input, _cli.phase_timeout_seconds(config, config.triage_timeout_seconds))
    triage_artifact = config.artifact_dir / f"triage-{iteration}.txt"
    _cli.write_artifact(triage_artifact, _cli._combined_output(result))
    _cli.record_model_charge(config, result, phase="triage", iteration=iteration, ctx=ctx)
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
        _cli.progress_event(config, "triage", str(iteration), "failed", f"exit {result.returncode}", ctx=ctx)
        raise RuntimeError(
            f"codex exec triage failed for iteration {iteration}; "
            f"see {triage_artifact}"
        )
    _cli.progress_event(config, "triage", str(iteration), "done", ctx=ctx)
    triage_output = actionable_review_output(_cli._combined_output(result))
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
            _cli.progress_event(config, "triage", str(iteration), "invalid", str(exc), ctx=ctx)
            if config.triage_on_invalid == "stop":
                raise RuntimeError(f"invalid structured triage output for iteration {iteration}: {exc}") from exc
            return review_output, 0, False, None
        suppressed_count = 0
        if config.suppressions_enabled:
            try:
                matches = suppressions.load_effective_suppressions(config.cwd)
            except (OSError, ValueError) as exc:
                _cli.progress_event(
                    config,
                    "triage",
                    str(iteration),
                    "warning",
                    f"suppressions unavailable; continuing without them: {exc}",
                    ctx=ctx,
                )
            else:
                payload, suppressed_findings = suppressions.apply_to_triage_payload(payload, matches)
                suppressed_count = len(suppressed_findings)
                if suppressed_findings:
                    _cli.progress_event(
                        config,
                        "triage",
                        str(iteration),
                        "suppressed",
                        f"{len(suppressed_findings)} finding(s)",
                        ctx=ctx,
                    )
        triage.write_triage_artifact(config.artifact_dir, iteration, payload)
        has_actionable_findings = bool(payload.get("confirmed_findings") or payload.get("needs_more_info"))
        if not has_actionable_findings:
            return "", suppressed_count, True, payload
        return triage.format_structured_handoff(payload, review_output), suppressed_count, False, payload
    return (
        "Triage handoff from the previous review:\n"
        f"{triage_output}\n\n"
        "Original review/check context:\n"
        f"{review_output}"
    ), 0, False, None
