"""Pure view-models for the live run monitor TUI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any

from code_review_loop import profiles, tui_loop_state, tui_state

RUNNER_PHASE_TO_DISPLAY: dict[str, str] = {
    "review": "review",
    "triage": "triage",
    "remediate": "remediation",
    "check": "checks",
    "commit": "commit",
}
RUN_STATE_GLYPHS: dict[str, str] = {
    "done": "✓",
    "failed": "✗",
    "running": "▶",
    "pending": "·",
    "disabled": "⤫",
}


@dataclass(frozen=True)
class RunPhaseStatus:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class RunLoopView:
    phases: tuple[RunPhaseStatus, ...]
    iteration: int | None
    max_iterations: int
    inner_retry: int
    inner_check_retries: int


@dataclass(frozen=True)
class RunIterationOutcome:
    iteration: int
    review: str
    remediation: str
    checks: str
    commit: str


@dataclass(frozen=True)
class RunOutcomeView:
    title: str
    headline: str
    explanation: str
    severity: str
    duration: str | None
    finished: str | None
    telemetry: str | None
    iterations: tuple[RunIterationOutcome, ...]
    retry_review: bool
    resumable: bool


def _phase_enabled_map(profile: profiles.Profile) -> dict[str, bool]:
    return {phase.name: phase.enabled for phase in tui_state.pipeline_phases(profile)}


def _outer_iteration(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        head = value.split(".", 1)[0]
        if head.isdecimal():
            return int(head)
    return None


def run_loop_view(
    records: tuple[Any, ...] | list[Any], profile: profiles.Profile
) -> RunLoopView:
    enabled = _phase_enabled_map(profile)
    states: dict[str, str] = {
        name: ("pending" if enabled.get(name, True) else "disabled")
        for name in tui_loop_state.LOOP_PHASES
    }
    details: dict[str, str] = {name: "" for name in tui_loop_state.LOOP_PHASES}
    iteration: int | None = None
    current_outer_iteration: int | None = None
    remediate_starts_this_iteration = 0
    last_remediate_iteration: int | None = None
    any_check_result = False
    last_check_status: str | None = None

    for event in records:
        event_outer_iteration = _outer_iteration(getattr(event, "iteration", None))
        if event_outer_iteration is not None:
            if (
                current_outer_iteration is not None
                and event_outer_iteration != current_outer_iteration
            ):
                for name, is_enabled in enabled.items():
                    if is_enabled or (name == "checks" and any_check_result):
                        states[name] = "pending"
                        details[name] = ""
                remediate_starts_this_iteration = 0
                last_remediate_iteration = None
                any_check_result = False
                last_check_status = None
            current_outer_iteration = event_outer_iteration
            iteration = event_outer_iteration

        phase = getattr(event, "phase", None) or ""
        display = RUNNER_PHASE_TO_DISPLAY.get(phase)
        kind = getattr(event, "kind", "")
        if display is not None and states.get(display) != "disabled":
            if kind == "phase_start":
                states[display] = "running"
                if display == "remediation":
                    if last_remediate_iteration != event_outer_iteration:
                        remediate_starts_this_iteration = 0
                        last_remediate_iteration = event_outer_iteration
                    remediate_starts_this_iteration += 1
            elif kind == "phase_result":
                states[display] = "done"
                detail = tui_state.event_detail(event)
                if detail:
                    details[display] = detail
            elif kind == "failure":
                states[display] = "failed"
                detail = tui_state.event_detail(event)
                if detail:
                    details[display] = detail

        if kind == "check_result":
            any_check_result = True
            payload = getattr(event, "payload", {})
            status = payload.get("status") if isinstance(payload, dict) else None
            if isinstance(status, str):
                normalized_status = status.lower()
                if normalized_status in {"passed", "failed"}:
                    if normalized_status == "failed":
                        last_check_status = "failed"
                    elif last_check_status is None:
                        last_check_status = "passed"
                    continue
            passed = payload.get("passed") if isinstance(payload, dict) else None
            if isinstance(passed, bool):
                if not passed:
                    last_check_status = "failed"
                elif last_check_status is None:
                    last_check_status = "passed"

    if any_check_result:
        states["checks"] = "done"
        if last_check_status == "failed":
            details["checks"] = "failed"
        elif last_check_status == "passed":
            details["checks"] = "passed"

    return RunLoopView(
        phases=tuple(
            RunPhaseStatus(name=name, state=states[name], detail=details[name])
            for name in tui_loop_state.LOOP_PHASES
        ),
        iteration=iteration,
        max_iterations=profile.pipeline.max_iterations,
        inner_retry=max(0, remediate_starts_this_iteration - 1),
        inner_check_retries=profile.runtime.inner_check_retries,
    )


def event_tail_lines(
    records: tuple[Any, ...] | list[Any], *, limit: int = 8
) -> tuple[str, ...]:
    if not records:
        return ()
    tail = records[-limit:]
    views = tui_state.event_views_from_events(tuple(tail))
    return tuple(tui_state.event_row_text(view) for view in views)


def run_outcome_view(summary: dict[str, object]) -> RunOutcomeView:
    """Turn the persisted terminal contract into operator-facing language."""
    status = str(summary.get("final_status") or "unknown")
    reason = str(summary.get("stopped_reason") or status)
    if reason == "review_unknown":
        title, headline, severity = "NEEDS ATTENTION", "Review inconclusive", "warning"
        explanation = _summary_text(summary, "latest_review_excerpt") or (
            "RevRem could not confidently classify the review, so it stopped "
            "without passing it to remediation."
        )
    elif status == "clear":
        title, headline, severity = "COMPLETE", "Review clear", "success"
        explanation = "No actionable findings remain."
    elif status == "findings":
        title, headline, severity = "ACTION NEEDED", "Findings remain", "warning"
        explanation = (
            "The run stopped with an actionable review that has not been remediated."
        )
    elif reason == "cancelled":
        title, headline, severity = "STOPPED", "Run cancelled", "warning"
        explanation = "The run stopped at a recorded boundary."
    elif reason in {"budget_ceiling_hit", "cost_ceiling_hit"}:
        title, headline, severity = "STOPPED", "Budget limit reached", "warning"
        explanation = "The configured run budget was exhausted."
    else:
        title, headline, severity = "FAILED", "Run did not complete", "error"
        explanation = _summary_text(summary, "error") or reason.replace("_", " ")

    duration_value = summary.get("duration_seconds")
    duration = (
        format_duration(float(duration_value))
        if isinstance(duration_value, (int, float))
        and not isinstance(duration_value, bool)
        else None
    )
    invocations = summary.get("model_invocations")
    tokens = summary.get("tokens")
    telemetry: list[str] = []
    if isinstance(invocations, list):
        telemetry.append(
            f"{len(invocations)} model call{'s' if len(invocations) != 1 else ''}"
        )
    token_total = tokens.get("total") if isinstance(tokens, dict) else tokens
    if isinstance(token_total, int) and not isinstance(token_total, bool):
        telemetry.append(f"{token_total:,} tokens")
    return RunOutcomeView(
        title=title,
        headline=headline,
        explanation=explanation,
        severity=severity,
        duration=duration,
        finished=format_finished_at(_summary_text(summary, "finished_at")),
        telemetry=" · ".join(telemetry) or None,
        iterations=_iteration_outcomes(summary, terminal_reason=reason),
        retry_review=reason == "review_unknown",
        resumable=reason
        in {
            "max_iterations_reached",
            "max_iterations_reached_with_check_failures",
            "budget_ceiling_hit",
            "cancelled",
        },
    )


def timeline_lines(
    records: tuple[Any, ...] | list[Any], *, local_tz: tzinfo | None = None
) -> tuple[str, ...]:
    """Render a chronological timeline and collapse adjacent artifact noise."""
    if not records:
        return ()
    zone = local_tz or datetime.now().astimezone().tzinfo or UTC
    parsed = [_event_datetime(str(getattr(record, "ts", ""))) for record in records]
    started = next((value for value in parsed if value is not None), None)
    lines: list[str] = []
    artifact_count = 0
    artifact_time: datetime | None = None

    def flush_artifacts() -> None:
        nonlocal artifact_count, artifact_time
        if artifact_count:
            lines.append(
                _timeline_line(
                    artifact_time,
                    started,
                    "-",
                    "ARTIFACTS",
                    f"{artifact_count} file{'s' if artifact_count != 1 else ''} written",
                    zone,
                )
            )
        artifact_count, artifact_time = 0, None

    for record, occurred in zip(records, parsed, strict=True):
        if getattr(record, "kind", "") == "artifact_write":
            artifact_count += 1
            artifact_time = occurred or artifact_time
            continue
        flush_artifacts()
        phase = str(getattr(record, "phase", None) or "run").upper()
        iteration = str(getattr(record, "iteration", None) or "-").split(".", 1)[0]
        kind = str(getattr(record, "kind", "event")).replace("_", " ")
        detail = tui_state.event_detail(record)
        description = f"{kind} · {detail}" if detail else kind
        lines.append(
            _timeline_line(occurred, started, iteration, phase, description, zone)
        )
    flush_artifacts()
    return tuple(lines)


def raw_event_lines(records: tuple[Any, ...] | list[Any]) -> tuple[str, ...]:
    return tuple(
        tui_state.event_row_text(view)
        for view in tui_state.event_views_from_events(tuple(records))
    )


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return (
        f"{hours}h {minutes:02d}m {secs:02d}s" if hours else f"{minutes}m {secs:02d}s"
    )


def format_finished_at(
    value: str | None, *, local_tz: tzinfo | None = None
) -> str | None:
    occurred = _event_datetime(value or "")
    if occurred is None:
        return None
    zone = local_tz or datetime.now().astimezone().tzinfo or UTC
    return occurred.astimezone(zone).strftime("%H:%M")


def _iteration_outcomes(
    summary: dict[str, object], *, terminal_reason: str
) -> tuple[RunIterationOutcome, ...]:
    raw = summary.get("iterations")
    if not isinstance(raw, list):
        return ()
    rows: list[RunIterationOutcome] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        number = item.get("iteration")
        iteration = number if isinstance(number, int) else index
        review = str(item.get("review_status") or "unknown")
        inconclusive = review == "unknown" or (
            terminal_reason == "review_unknown" and index == len(raw)
        )
        if inconclusive:
            remediation = checks = commit = "not run"
        else:
            remediation = (
                "done"
                if item.get("remediated") is not False
                and (review == "findings" or item.get("checks"))
                else "skipped"
            )
            failures = item.get("check_failures")
            checks = (
                "failed"
                if isinstance(failures, int) and failures > 0
                else ("passed" if item.get("checks") or failures == 0 else "not run")
            )
            commit = (
                "committed"
                if item.get("committed")
                or item.get("commit")
                or item.get("commit_status") == "committed"
                else "not run"
            )
        rows.append(RunIterationOutcome(iteration, review, remediation, checks, commit))
    return tuple(rows)


def _summary_text(summary: dict[str, object], key: str) -> str | None:
    value = summary.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _event_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _timeline_line(
    occurred: datetime | None,
    started: datetime | None,
    iteration: str,
    phase: str,
    description: str,
    local_tz: tzinfo,
) -> str:
    wall = (
        occurred.astimezone(local_tz).strftime("%H:%M:%S") if occurred else "--:--:--"
    )
    elapsed = (
        int(max(0, (occurred - started).total_seconds())) if occurred and started else 0
    )
    return f"{wall}  +{elapsed:>4}s  {iteration:>2}  {phase:<11}  {description}"
