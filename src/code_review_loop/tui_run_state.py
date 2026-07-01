"""Pure view-models for the live run monitor TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from code_review_loop import profiles, tui_loop_state, tui_state

RUNNER_PHASE_TO_DISPLAY: dict[str, str] = {
    "review": "review",
    "triage": "triage",
    "remediate": "remediation",
    "commit": "commit",
}
RUN_STATE_GLYPHS: dict[str, str] = {
    "done": "✓",
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
    last_check_passed: bool | None = None

    for event in records:
        event_outer_iteration = _outer_iteration(getattr(event, "iteration", None))
        if event_outer_iteration is not None:
            if (
                current_outer_iteration is not None
                and event_outer_iteration != current_outer_iteration
            ):
                for name, is_enabled in enabled.items():
                    if is_enabled:
                        states[name] = "pending"
                        details[name] = ""
                remediate_starts_this_iteration = 0
                last_remediate_iteration = None
                any_check_result = False
                last_check_passed = None
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

        if kind == "check_result":
            any_check_result = True
            payload = getattr(event, "payload", {})
            passed = payload.get("passed") if isinstance(payload, dict) else None
            if isinstance(passed, bool):
                last_check_passed = passed

    if states.get("checks") != "disabled" and any_check_result:
        states["checks"] = "done"
        if last_check_passed is False:
            details["checks"] = "failed"
        elif last_check_passed is True:
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
