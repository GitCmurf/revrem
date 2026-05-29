"""Resume support for event-backed RevRem runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

from code_review_loop import budgets, diagnostics, events, profiles, reporting
from code_review_loop.adapters.git import git_preflight_stdout
from code_review_loop.config import LoopConfig

RESUMABLE_STOPPED_REASONS = frozenset(
    {
        "max_iterations_reached",
        "max_iterations_reached_with_check_failures",
        "budget_ceiling_hit",
        "cancelled",
    }
)


def resume_precondition_issues(run_dir: Path, *, cwd: Path) -> list[diagnostics.DiagnosticIssue]:
    summary_path = run_dir / "summary.json"
    events_path = run_dir / events.EVENTS_FILENAME
    issues: list[diagnostics.DiagnosticIssue] = []
    if not summary_path.is_file():
        return [
            diagnostics.DiagnosticIssue(
                code="revrem.resume.missing_summary",
                severity="blocking",
                message="Resume requires summary.json in the run directory.",
                hint="Pass a RevRem run directory that contains summary.json.",
                evidence={"path": str(summary_path)},
            )
        ]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("summary.json must contain a JSON object")
    issues.extend(resume_budget_ceiling_issues(summary))
    if latest_resume_review_path(summary, run_dir=run_dir) is None:
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.missing_review_artifact",
                severity="blocking",
                message="Resume requires a previous review artifact.",
                hint="Only runs with a review artifact can continue without re-running completed review phases.",
                evidence={"run_dir": str(run_dir)},
            )
        )
    if not isinstance(summary.get("resume_config"), dict):
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.missing_config",
                severity="blocking",
                message="Resume requires resume_config from the original run.",
                hint="Run a fresh RevRem loop with a version that records resume_config.",
                evidence={},
            )
        )
    reason = summary.get("stopped_reason")
    if reason not in RESUMABLE_STOPPED_REASONS:
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.not_resumable",
                severity="blocking",
                message="The run did not stop at a resumable boundary.",
                hint="Only max-iteration, budget, and cancellation boundaries are resumable.",
                evidence={"stopped_reason": reason},
            )
        )
    if not events_path.is_file():
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.missing_events",
                severity="blocking",
                message="Resume requires events.jsonl in the run directory.",
                hint="Only event-backed runs can be resumed safely.",
                evidence={"path": str(events_path)},
            )
        )
    else:
        records, truncated = events.read_events(events_path)
        if truncated:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.resume.truncated_events",
                    severity="blocking",
                    message="Resume requires a complete events.jsonl stream.",
                    hint="Inspect the run manually; the event stream ended with a truncated line.",
                    evidence={"path": str(events_path)},
                )
            )
        if not records or records[-1].kind not in {"summary", "failure", "cancellation", "cost_ceiling_hit"}:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.resume.unclean_event_boundary",
                    severity="blocking",
                    message="The event stream is empty or does not end at a clean phase boundary.",
                    hint="Resume is only allowed after a summary, failure, cancellation, or ceiling event.",
                    evidence={"last_event_kind": records[-1].kind if records else None},
                )
            )
    issues.extend(resume_git_state_issues(summary, cwd=cwd))
    return issues


def resume_budget_ceiling_issues(summary: dict[str, object]) -> list[diagnostics.DiagnosticIssue]:
    """Block resumes that would immediately re-enter a persisted wall, token, or USD ceiling."""
    resume_config = summary.get("resume_config")
    budgets_payload = summary.get("budgets")
    if not isinstance(resume_config, dict) or not isinstance(budgets_payload, dict):
        return []

    issues: list[diagnostics.DiagnosticIssue] = []
    max_wall_seconds = _resume_budget_field(
        resume_config,
        budgets_payload,
        "max_wall_seconds",
        _resume_optional_float,
    )
    wall_elapsed_seconds = _resume_wall_elapsed_seconds(summary, budgets_payload)
    if (
        max_wall_seconds is not None
        and wall_elapsed_seconds is not None
        and wall_elapsed_seconds >= max_wall_seconds
    ):
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.wall_budget_exhausted",
                severity="blocking",
                message="Resume requires remaining wall budget headroom.",
                hint="Start a new run or raise the persisted wall ceiling before resuming.",
                evidence={"used": wall_elapsed_seconds, "limit": max_wall_seconds},
            )
        )

    max_tokens = _resume_budget_field(
        resume_config,
        budgets_payload,
        "max_tokens",
        _resume_optional_int,
    )
    tokens_used = budgets_payload.get("tokens")
    if (
        isinstance(tokens_used, int)
        and not isinstance(tokens_used, bool)
        and max_tokens is not None
        and tokens_used >= max_tokens
    ):
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.token_budget_exhausted",
                severity="blocking",
                message="Resume requires remaining token budget headroom.",
                hint="Start a new run or raise the persisted token ceiling before resuming.",
                evidence={"used": tokens_used, "limit": max_tokens},
            )
        )

    max_usd = _resume_budget_field(
        resume_config,
        budgets_payload,
        "max_usd",
        _resume_optional_decimal,
    )
    used_usd = _resume_optional_decimal(budgets_payload, "usd")
    if used_usd is not None and max_usd is not None and used_usd >= max_usd:
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.usd_budget_exhausted",
                severity="blocking",
                message="Resume requires remaining USD budget headroom.",
                hint="Start a new run or raise the persisted USD ceiling before resuming.",
                evidence={"used": str(used_usd), "limit": str(max_usd)},
            )
        )

    return issues


def resume_loop_config(
    summary: dict[str, object], *, run_dir: Path, cwd: Path | None = None
) -> tuple[LoopConfig, budgets.BudgetState | None]:
    cwd = cwd or Path.cwd()
    resume_config = summary.get("resume_config")
    if not isinstance(resume_config, dict):
        raise ValueError("summary.json is missing resume_config")
    budgets_payload = summary.get("budgets")
    review_path = latest_resume_review_path(summary, run_dir=run_dir)
    if review_path is None:
        raise ValueError("summary.json is missing a resumable review artifact")
    budget_state = _resume_budget_state(summary)
    budget_issues = resume_budget_ceiling_issues(summary)
    if budget_issues:
        raise ValueError("; ".join(issue.message for issue in budget_issues))
    profile_name = _resume_optional_str(resume_config, "profile_name")
    if profile_name is None and isinstance(summary.get("profile"), str):
        profile_name = str(summary["profile"])
    profile_v2 = _resume_profile_v2(resume_config, profile_name)
    triage_contract = _resume_str(resume_config, "triage_contract", "v1")
    if profile_v2 is not None:
        triage_contract = profile_v2.triage.contract
    return LoopConfig(
        base=_resume_str(resume_config, "base", "main"),
        max_iterations=_resume_int(resume_config, "max_iterations", 1),
        codex_bin=_resume_str(resume_config, "codex_bin", "codex"),
        harness_executables=_resume_str_dict(resume_config, "harness_executables"),
        cwd=cwd,
        artifact_dir=run_dir,
        review_harness=_resume_str(resume_config, "review_harness", "codex"),
        remediation_harness=_resume_str(resume_config, "remediation_harness", "codex"),
        triage_harness=_resume_str(resume_config, "triage_harness", "codex"),
        review_model=_resume_optional_str(resume_config, "review_model"),
        remediation_model=_resume_optional_str(resume_config, "remediation_model"),
        triage_model=_resume_optional_str(resume_config, "triage_model"),
        reasoning_effort=_resume_optional_str(resume_config, "reasoning_effort"),
        review_reasoning_effort=_resume_optional_str(resume_config, "review_reasoning_effort"),
        remediation_reasoning_effort=_resume_optional_str(resume_config, "remediation_reasoning_effort"),
        triage_reasoning_effort=_resume_optional_str(resume_config, "triage_reasoning_effort"),
        triage_enabled=_resume_bool(resume_config, "triage_enabled", False),
        final_review=_resume_bool(resume_config, "final_review", True),
        timeout_seconds=_resume_optional_float(resume_config, "timeout_seconds"),
        review_timeout_seconds=_resume_optional_float(resume_config, "review_timeout_seconds"),
        remediation_timeout_seconds=_resume_optional_float(resume_config, "remediation_timeout_seconds"),
        triage_timeout_seconds=_resume_optional_float(resume_config, "triage_timeout_seconds"),
        timeout_seconds_display=_resume_phase_timeout(resume_config, "checks"),
        review_timeout_seconds_display=_resume_phase_timeout(resume_config, "review"),
        remediation_timeout_seconds_display=_resume_phase_timeout(resume_config, "remediation"),
        triage_timeout_seconds_display=_resume_phase_timeout(resume_config, "triage"),
        debug_status_detection=_resume_bool(resume_config, "debug_status_detection", False),
        progress_style=_resume_str(resume_config, "progress_style", "compact"),
        terminal_excerpt_chars=_resume_int(resume_config, "terminal_excerpt_chars", 4_000),
        max_remediation_input_chars=_resume_int(resume_config, "max_remediation_input_chars", 200_000),
        check_commands=_resume_str_tuple(resume_config, "check_commands"),
        commit_after_remediation=_resume_bool(resume_config, "commit_after_remediation", False),
        commit_message_harness=_resume_str(resume_config, "commit_message_harness", "codex"),
        commit_message_model=_resume_optional_str(resume_config, "commit_message_model"),
        commit_message_prompt=_resume_optional_str(resume_config, "commit_message_prompt"),
        commit_message_prompt_overridden=_resume_bool(
            resume_config, "commit_message_prompt_overridden", False
        ),
        commit_on_hook_failure=_resume_str(resume_config, "commit_on_hook_failure", "remediate"),
        commit_reasoning_effort=_resume_optional_str(resume_config, "commit_reasoning_effort"),
        commit_timeout_seconds=_resume_optional_float(resume_config, "commit_timeout_seconds"),
        commit_timeout_seconds_display=_resume_phase_timeout(resume_config, "commit_message"),
        exec_sandbox=_resume_str(resume_config, "exec_sandbox", "workspace-write"),
        exec_json=_resume_bool(resume_config, "exec_json", False),
        output_last_message=_resume_bool(resume_config, "output_last_message", True),
        full_auto=_resume_bool(resume_config, "full_auto", True),
        trusted_repo=_resume_bool(resume_config, "trusted_repo", False),
        triage_prompt=_resume_optional_str(resume_config, "triage_prompt"),
        triage_on_invalid=_resume_str(resume_config, "triage_on_invalid", "continue"),
        triage_contract=triage_contract,
        initial_review_file=review_path,
        profile_name=profile_name,
        budget_config=_resume_budget_config(resume_config, budgets_payload if isinstance(budgets_payload, dict) else None),
        profile_v2=profile_v2,
        phase_config_sources=_resume_phase_sources(resume_config),
        phase_config_field_sources=_resume_phase_field_sources(resume_config),
    ), budget_state


def resume_config_payload(config: LoopConfig) -> dict[str, object]:
    """Persist the loop inputs required to resume with the same safety envelope."""
    payload: dict[str, object] = {
        "base": config.base,
        "max_iterations": config.max_iterations,
        "codex_bin": config.codex_bin,
        "harness_executables": dict(config.harness_executables),
        "review_harness": config.review_harness,
        "remediation_harness": config.remediation_harness,
        "triage_harness": config.triage_harness,
        "review_model": config.review_model or config.model,
        "remediation_model": config.remediation_model or config.model,
        "triage_model": config.triage_model,
        "triage_enabled": config.triage_enabled,
        "final_review": config.final_review,
        "check_commands": list(config.check_commands),
        "timeout_seconds": config.timeout_seconds_display,
        "review_timeout_seconds": config.review_timeout_seconds_display,
        "remediation_timeout_seconds": config.remediation_timeout_seconds_display,
        "triage_timeout_seconds": config.triage_timeout_seconds_display,
        "phase_config": reporting.phase_config_payload(config),
        "progress_style": config.progress_style,
        "debug_status_detection": config.debug_status_detection,
        "terminal_excerpt_chars": config.terminal_excerpt_chars,
        "max_remediation_input_chars": config.max_remediation_input_chars,
        "commit_after_remediation": config.commit_after_remediation,
        "commit_on_hook_failure": config.commit_on_hook_failure,
        "exec_sandbox": config.exec_sandbox,
        "exec_json": config.exec_json,
        "output_last_message": config.output_last_message,
        "full_auto": config.full_auto,
        "max_wall_seconds": config.budget_config.max_wall_seconds,
        "max_tokens": config.budget_config.max_tokens,
        "max_usd": str(config.budget_config.max_usd) if config.budget_config.max_usd is not None else None,
        "soft_warn_fraction": config.budget_config.soft_warn_fraction,
        "triage_prompt": config.triage_prompt,
        "triage_on_invalid": config.triage_on_invalid,
        "triage_contract": config.triage_contract,
        "profile_name": config.profile_name,
    }
    _put_if_not_none(payload, "reasoning_effort", config.reasoning_effort)
    _put_if_not_none(payload, "review_reasoning_effort", config.review_reasoning_effort)
    _put_if_not_none(payload, "remediation_reasoning_effort", config.remediation_reasoning_effort)
    _put_if_not_none(payload, "triage_reasoning_effort", config.triage_reasoning_effort)
    _put_if_not_default(payload, "commit_message_harness", config.commit_message_harness, "codex")
    _put_if_not_none(payload, "commit_message_model", config.commit_message_model)
    _put_if_not_none(payload, "commit_message_prompt", config.commit_message_prompt)
    _put_if_not_default(
        payload,
        "commit_message_prompt_overridden",
        config.commit_message_prompt_overridden,
        False,
    )
    _put_if_not_default(payload, "trusted_repo", config.trusted_repo, False)
    _put_if_not_none(payload, "commit_reasoning_effort", config.commit_reasoning_effort)
    _put_if_not_none(payload, "commit_timeout_seconds", config.commit_timeout_seconds)
    _put_if_not_none(payload, "profile_v2", _resume_profile_snapshot(config))
    return payload


def _put_if_not_none(payload: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        payload[key] = value


def _put_if_not_default(payload: dict[str, object], key: str, value: object, default: object) -> None:
    if value != default:
        payload[key] = value


def _resume_profile_snapshot(config: LoopConfig) -> dict[str, object] | None:
    """Persist immutable v2 routing inputs needed after profile files change."""
    if config.profile_v2 is None:
        return None
    return {
        "name": config.profile_v2.name,
        "triage": asdict(config.profile_v2.triage),
    }


def _resume_profile_v2(
    resume_config: dict[object, object],
    profile_name: str | None,
) -> profiles.Profile | None:
    profile_payload = resume_config.get("profile_v2")
    if not isinstance(profile_payload, dict):
        return None
    triage_payload = profile_payload.get("triage")
    if not isinstance(triage_payload, dict):
        return None
    name = _resume_optional_str(profile_payload, "name") or profile_name or ""
    return profiles.Profile(
        name=name,
        triage=profiles.parse_triage(triage_payload, "resume_config.profile_v2.triage"),
        source="summary.json",
    )


def latest_resume_review_path(summary: dict[str, object], *, run_dir: Path) -> Path | None:
    artifact_paths = summary.get("artifact_paths")
    if not isinstance(artifact_paths, dict):
        return None
    reviews = artifact_paths.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        return None
    for item in reversed(reviews):
        if isinstance(item, str):
            path = Path(item)
            if not path.is_absolute():
                legacy_path = run_dir / path.name
                if legacy_path.is_file():
                    return legacy_path
            if path.is_file():
                return path
    return None


def resume_git_state_issues(summary: dict[str, object], *, cwd: Path) -> list[diagnostics.DiagnosticIssue]:
    git_state = summary.get("git_state")
    if not isinstance(git_state, dict) or not git_state.get("available"):
        return [
            diagnostics.DiagnosticIssue(
                code="revrem.resume.missing_git_state",
                severity="blocking",
                message="Resume requires summary git_state from the original run.",
                hint="Run a fresh RevRem loop with a version that records git_state.",
                evidence={},
            )
        ]
    expected_head = git_state.get("head")
    expected_base = git_state.get("base")
    expected_base_commit = git_state.get("base_commit")
    current_head = git_preflight_stdout(cwd, ["rev-parse", "HEAD"])
    current_base_commit = (
        git_preflight_stdout(cwd, ["rev-parse", "--verify", f"{expected_base}^{{commit}}"])
        if isinstance(expected_base, str)
        else None
    )
    issues: list[diagnostics.DiagnosticIssue] = []
    if current_head != expected_head:
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.head_mismatch",
                severity="blocking",
                message="Current HEAD does not match the original run.",
                hint="Check out the same commit before resuming.",
                evidence={"expected": expected_head, "actual": current_head},
            )
        )
    if current_base_commit != expected_base_commit:
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.resume.base_mismatch",
                severity="blocking",
                message="Current base commit does not match the original run.",
                hint="Restore or fetch the original base ref before resuming.",
                evidence={"base": expected_base, "expected": expected_base_commit, "actual": current_base_commit},
            )
        )
    return issues


def _resume_str(payload: dict[object, object], key: str, fallback: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else fallback


def _resume_optional_str(payload: dict[object, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _resume_bool(payload: dict[object, object], key: str, fallback: bool) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else fallback


def _resume_int(payload: dict[object, object], key: str, fallback: int) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _resume_optional_int(payload: dict[object, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _resume_optional_float(payload: dict[object, object], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _resume_phase_timeout(payload: dict[object, object], phase: str) -> float | None:
    phase_config = payload.get("phase_config")
    if not isinstance(phase_config, dict):
        return None
    section = phase_config.get(phase)
    if not isinstance(section, dict):
        return None
    value = section.get("timeout_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _resume_phase_sources(payload: dict[object, object]) -> dict[str, str]:
    phase_config = payload.get("phase_config")
    if not isinstance(phase_config, dict):
        return {}
    sources: dict[str, str] = {}
    for phase in ("review", "triage", "remediation", "commit_message", "checks"):
        section = phase_config.get(phase)
        if not isinstance(section, dict):
            continue
        source = section.get("source")
        if isinstance(source, str):
            sources[phase] = source
    return sources


def _resume_phase_field_sources(payload: dict[object, object]) -> dict[str, dict[str, str]]:
    phase_config = payload.get("phase_config")
    if not isinstance(phase_config, dict):
        return {}
    field_sources: dict[str, dict[str, str]] = {}
    for phase in ("review", "triage", "remediation", "commit_message", "checks"):
        section = phase_config.get(phase)
        if not isinstance(section, dict):
            continue
        sources = section.get("sources")
        if not isinstance(sources, dict):
            continue
        field_sources[phase] = {
            str(field): source
            for field, source in sources.items()
            if isinstance(source, str)
        }
    return field_sources


def _resume_str_tuple(payload: dict[object, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _resume_str_dict(payload: dict[object, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(k): v
        for k, v in value.items()
        if isinstance(k, str) and isinstance(v, str)
    }


_T = TypeVar("_T")


def _resume_budget_field(
    payload: dict[object, object],
    budgets_payload: dict[object, object] | None,
    key: str,
    parser: Callable[[dict[object, object], str], _T | None],
) -> _T | None:
    value = parser(payload, key)
    if value is not None or not isinstance(budgets_payload, dict):
        return value
    return parser(budgets_payload, key)


def _resume_budget_config(
    payload: dict[object, object],
    budgets_payload: dict[object, object] | None = None,
) -> budgets.BudgetConfig:
    """Rebuild persisted run ceilings for safe resumes, including legacy budget payloads."""
    soft_warn_fraction = _resume_budget_field(
        payload,
        budgets_payload,
        "soft_warn_fraction",
        _resume_optional_float,
    )
    budget_config = budgets.BudgetConfig(
        max_wall_seconds=_resume_budget_field(
            payload,
            budgets_payload,
            "max_wall_seconds",
            _resume_optional_float,
        ),
        max_tokens=_resume_budget_field(
            payload,
            budgets_payload,
            "max_tokens",
            _resume_optional_int,
        ),
        max_usd=_resume_budget_field(
            payload,
            budgets_payload,
            "max_usd",
            _resume_optional_decimal,
        ),
        soft_warn_fraction=soft_warn_fraction if soft_warn_fraction is not None else 0.8,
    )
    budgets.validate_config(budget_config)
    return budget_config


def _resume_budget_state(summary: dict[str, object]) -> budgets.BudgetState | None:
    """Restore spent wall, token, and USD totals from the previous run."""
    budgets_payload = summary.get("budgets")
    if not isinstance(budgets_payload, dict):
        return None
    state = budgets.started_now()
    seeded = False
    wall_elapsed_seconds = _resume_wall_elapsed_seconds(summary, budgets_payload)
    if wall_elapsed_seconds is not None:
        state.started_at_monotonic -= wall_elapsed_seconds
        seeded = True
    tokens = budgets_payload.get("tokens")
    if isinstance(tokens, int) and not isinstance(tokens, bool):
        state.tokens_used = tokens
        state.tokens_reported = True
        seeded = True
    parsed_usd = _resume_optional_decimal(budgets_payload, "usd")
    if parsed_usd is not None:
        state.usd_used = parsed_usd
        state.usd_reported = True
        seeded = True
    return state if seeded else None


def _resume_wall_elapsed_seconds(
    summary: dict[str, object],
    budgets_payload: dict[object, object] | None,
) -> float | None:
    wall_elapsed_seconds = _resume_budget_field(
        summary,  # type: ignore[arg-type]
        budgets_payload,
        "wall_elapsed_seconds",
        _resume_optional_float,
    )
    if wall_elapsed_seconds is not None:
        return wall_elapsed_seconds
    return _resume_optional_float(summary, "duration_seconds")  # type: ignore[arg-type]


def _resume_optional_decimal(payload: dict[object, object], key: str) -> Decimal | None:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        raise ValueError(
            f"resume_config.{key} must be a decimal string, not float"
        )
    if isinstance(value, (str, int, Decimal)):
        return budgets.parse_usd(str(value))
    return None
