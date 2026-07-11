"""Pure view-models for the editable loop TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from code_review_loop import harnesses, profiles, tui_state
from code_review_loop.config import DEFAULT_TIMEOUT_SECONDS

LOOP_PHASES: tuple[str, ...] = ("review", "triage", "remediation", "checks", "commit")
PHASE_ENABLED_GLYPH = "●"
PHASE_DISABLED_GLYPH = "○"
PHASE_DOTTED: dict[str, dict[str, str]] = {
    "review": {
        "harness": "review.harness",
        "model": "review.model",
        "effort": "review.reasoning_effort",
        "timeout": "review.timeout_seconds",
    },
    "triage": {
        "enabled": "triage.enabled",
        "harness": "triage.harness",
        "model": "triage.model",
        "effort": "triage.reasoning_effort",
        "timeout": "triage.timeout_seconds",
        "routing_default": "triage.routing.default_route",
        "routing_strict": "triage.routing.strict_on_unavailable_route",
        "routing_escalate": "triage.routing.allow_model_escalation",
    },
    "remediation": {
        "harness": "remediation.harness",
        "model": "remediation.model",
        "effort": "remediation.reasoning_effort",
        "timeout": "remediation.timeout_seconds",
    },
    "checks": {},
    "commit": {
        "enabled": "commit.enabled",
        "harness": "commit.harness",
        "model": "commit.message_model",
        "effort": "commit.reasoning_effort",
        "timeout": "commit.timeout_seconds",
    },
}
LOOP_META_DOTTED = {
    "max_iterations": "pipeline.max_iterations",
    "final_review": "pipeline.final_review",
    "inner_check_retries": "runtime.inner_check_retries",
}


@dataclass(frozen=True)
class LoopRailMeta:
    max_iterations: int
    inner_retries: int
    inner_rail: bool
    final_review: bool
    outer_return_label: str
    inner_return_label: str | None
    final_review_label: str | None


@dataclass(frozen=True)
class TriageRouteRow:
    name: str
    harness: object
    model: object
    effort: object
    timeout: object
    sandbox: object
    fallback: object
    selected: bool


def _profile(source: Any) -> profiles.Profile:
    if hasattr(source, "profile"):
        return cast(profiles.Profile, source.profile)
    return cast(profiles.Profile, source)


def _effective_value(source: Any, dotted_key: str, fallback: object) -> object:
    field_value = getattr(source, "field_value", None)
    if callable(field_value):
        return field_value(dotted_key, fallback)
    return fallback


def _effective_bool(source: Any, dotted_key: str, fallback: bool) -> bool:
    value = _effective_value(source, dotted_key, fallback)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return bool(value)


def _effective_int(source: Any, dotted_key: str, fallback: int) -> int:
    value = _effective_value(source, dotted_key, fallback)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return fallback


def _format_timeout(value: object) -> str:
    if value is None or value == "":
        return f"{DEFAULT_TIMEOUT_SECONDS}s default"
    if isinstance(value, int | float):
        if value == 0:
            return "unbounded"
        return f"{value:g}s"
    if value == "0":
        return "unbounded"
    return f"{value}s"


def _phase_map(profile: profiles.Profile) -> dict[str, tui_state.PhaseView]:
    return {phase.name: phase for phase in tui_state.pipeline_phases(profile)}


def loop_header_text(source: Any) -> str:
    profile = _profile(source)
    max_iterations = _effective_int(
        source, LOOP_META_DOTTED["max_iterations"], profile.pipeline.max_iterations
    )
    inner_retries = _effective_int(
        source,
        LOOP_META_DOTTED["inner_check_retries"],
        profile.runtime.inner_check_retries,
    )
    final_review = _effective_bool(
        source, LOOP_META_DOTTED["final_review"], profile.pipeline.final_review
    )
    final_text = "final review on" if final_review else "final review off"
    dirty = " *" if bool(getattr(source, "is_dirty", False)) else ""
    return "\n".join(
        (
            "LOOP",
            (
                f"profile {profile.name}{dirty} | base {profile.pipeline.base} | "
                f"max {max_iterations} | inner retries {inner_retries} | {final_text}"
            ),
        )
    )


def loop_rail_meta(source: Any) -> LoopRailMeta:
    profile = _profile(source)
    max_iterations = _effective_int(
        source, LOOP_META_DOTTED["max_iterations"], profile.pipeline.max_iterations
    )
    inner_retries = _effective_int(
        source,
        LOOP_META_DOTTED["inner_check_retries"],
        profile.runtime.inner_check_retries,
    )
    final_review = _effective_bool(
        source, LOOP_META_DOTTED["final_review"], profile.pipeline.final_review
    )
    return LoopRailMeta(
        max_iterations=max_iterations,
        inner_retries=inner_retries,
        inner_rail=inner_retries > 0,
        final_review=final_review,
        outer_return_label=f"repeat while iteration < {max_iterations}",
        inner_return_label=(
            f"up to {inner_retries} inner retries" if inner_retries > 0 else None
        ),
        final_review_label="final review" if final_review else None,
    )


def phase_gutter(phase: str, rail_meta: LoopRailMeta) -> str:
    if phase == "review":
        return "01"
    if phase == "remediation" and rail_meta.inner_rail:
        return "03"
    if phase == "checks" and rail_meta.inner_rail:
        return "04"
    if phase == "commit":
        lines = ["05"]
        if rail_meta.final_review and rail_meta.final_review_label:
            lines.append("FR")
        return "\n".join(lines)
    return {
        "triage": "02",
        "remediation": "03",
        "checks": "04",
    }.get(phase, "  ")


def loop_return_lines(source: Any) -> tuple[str, ...]:
    meta = loop_rail_meta(source)
    lines: list[str] = []
    if meta.inner_rail and meta.inner_return_label:
        lines.append(f"INNER RETRY  checks -> remediation  ({meta.inner_return_label})")
    lines.append(f"OUTER LOOP   commit -> review      ({meta.outer_return_label})")
    if meta.final_review and meta.final_review_label:
        lines.append(f"FINAL        {meta.final_review_label}")
    return tuple(lines)


def phase_card_lines(
    source: Any, phase_name: str, *, focused: bool, expanded: bool
) -> tuple[str, ...]:
    profile = _profile(source)
    phases = _phase_map(profile)
    phase = phases[phase_name]
    dotted = PHASE_DOTTED[phase_name]
    enabled = (
        _effective_bool(source, dotted.get("enabled", ""), phase.enabled)
        if dotted.get("enabled")
        else phase.enabled
    )
    harness = _effective_value(source, dotted.get("harness", ""), phase.harness)
    model = _effective_value(source, dotted.get("model", ""), phase.model)
    effort = _effective_value(source, dotted.get("effort", ""), phase.reasoning_effort)
    timeout = _effective_value(source, dotted.get("timeout", ""), phase.timeout_seconds)
    marker = PHASE_ENABLED_GLYPH if enabled else PHASE_DISABLED_GLYPH
    arrow = "▾" if expanded else "▸"
    focus = ">" if focused else " "
    phase_label = phase_name.upper()
    if phase_name == "checks":
        checks = _effective_value(source, "pipeline.checks", profile.pipeline.checks)
        commands_tuple = (
            tuple(item for item in checks if isinstance(item, str))
            if isinstance(checks, list | tuple)
            else profile.pipeline.checks
        )
        commands = len(commands_tuple)
        timeout = _effective_value(
            source,
            "pipeline.check_timeout_seconds",
            profile.pipeline.check_timeout_seconds,
        )
        summary = (
            f"{focus}{arrow} {marker} {phase_label:<11} | {commands} commands | "
            f"{_format_timeout(timeout)}"
        )
        if not expanded:
            return (summary,)
        lines = [
            summary,
            f"  commands: {commands} commands",
            f"  timeout: {_format_timeout(timeout)}",
        ]
        lines.extend(f"  {index}. {command}" for index, command in enumerate(commands_tuple, start=1))
        lines.append("  e edit commands · t timeout · i max iterations · I inner retries")
        return tuple(lines)
    summary_parts = [str(harness or "-")]
    if model:
        summary_parts.append(str(model))
    effort_text = harnesses.phase_effort_text(
        str(harness) if harness else None, str(effort) if effort else None
    )
    if effort_text:
        summary_parts.append(effort_text)
    summary_parts.append(_format_timeout(timeout))
    summary = f"{focus}{arrow} {marker} {phase_label:<11} | " + " | ".join(summary_parts)
    if not expanded:
        return (summary,)
    lines = [
        summary,
        f"  harness: {harness or '-'}",
        f"  model: {model or 'provider default'}",
        f"  effort: {effort or 'model default'}",
        f"  timeout: {_format_timeout(timeout)}",
    ]
    if "enabled" in dotted:
        lines.insert(1, f"  enabled: {enabled}")
    if phase_name == "triage":
        routing = profile.triage.routing
        default_route = _effective_value(
            source, dotted["routing_default"], routing.default_route
        )
        strict = _effective_value(
            source, dotted["routing_strict"], routing.strict_on_unavailable_route
        )
        escalate = _effective_value(
            source, dotted["routing_escalate"], routing.allow_model_escalation
        )
        lines.extend(
            (
                f"  route default: {default_route}",
                f"  strict unavailable route: {strict}",
                f"  allow escalation: {escalate}",
            )
        )
    return tuple(lines)


def triage_routes_lines(
    source: Any, *, selected_route: str | None = None
) -> tuple[str, ...]:
    profile = _profile(source)
    # Respect unsaved editor overrides for routing enablement while editing.
    if not _effective_bool(source, "triage.routing.enabled", profile.triage.routing.enabled):
        return ()
    routing = profile.triage.routing
    default_route = _effective_value(
        source, "triage.routing.default_route", routing.default_route
    )
    strict = _effective_bool(
        source,
        "triage.routing.strict_on_unavailable_route",
        routing.strict_on_unavailable_route,
    )
    escalate = _effective_bool(
        source,
        "triage.routing.allow_model_escalation",
        routing.allow_model_escalation,
    )
    lines = [
        "routing: "
        f"default {default_route} · strict {strict} · "
        f"escalate {escalate}"
    ]
    remediation_timeout = _effective_value(
        source,
        "remediation.timeout_seconds",
        profile.remediation.timeout_seconds,
    )
    for row in triage_route_rows(source, selected_route=selected_route):
        effort_text = harnesses.phase_effort_text(
            str(row.harness) if row.harness else None,
            str(row.effort) if row.effort else None,
        )
        pointer = (
            f"{'>' if row.selected else ' '} " if selected_route is not None else ""
        )
        route_timeout = (
            f"inherit {_format_timeout(remediation_timeout)}"
            if row.timeout is None or row.timeout == ""
            else _format_timeout(row.timeout)
        )
        lines.append(
            f"{pointer}{row.name}: {row.harness} · {row.model or 'provider default'} · "
            f"{effort_text or 'model default'} · {route_timeout} · "
            f"{row.sandbox} · fallback {row.fallback or 'drop'}"
        )
    return tuple(lines)


def triage_route_rows(
    source: Any, *, selected_route: str | None = None
) -> tuple[TriageRouteRow, ...]:
    profile = _profile(source)
    rows: list[TriageRouteRow] = []
    route_names = set(profile.triage.routes)
    edits = getattr(source, "edits", None)
    if isinstance(edits, dict):
        for key in edits:
            if key.startswith("triage.routes."):
                parts = key.split(".")
                if len(parts) >= 4 and parts[2]:
                    route_names.add(parts[2])
    for name in sorted(route_names):
        route = profile.triage.routes.get(name)
        prefix = f"triage.routes.{name}"
        rows.append(
            TriageRouteRow(
                name=name,
                harness=_effective_value(
                    source, f"{prefix}.harness", route.harness if route else None
                ),
                model=_effective_value(
                    source, f"{prefix}.model", route.model if route else None
                ),
                effort=_effective_value(
                    source,
                    f"{prefix}.reasoning_effort",
                    route.reasoning_effort if route else None,
                ),
                timeout=_effective_value(
                    source,
                    f"{prefix}.timeout_seconds",
                    route.timeout_seconds if route else None,
                ),
                sandbox=_effective_value(
                    source, f"{prefix}.sandbox", route.sandbox if route else None
                ),
                fallback=_effective_value(
                    source, f"{prefix}.fallback", route.fallback if route else None
                ),
                selected=name == selected_route,
            )
        )
    return tuple(rows)
