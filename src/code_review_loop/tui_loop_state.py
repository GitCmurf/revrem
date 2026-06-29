"""Pure view-models for the editable loop TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from code_review_loop import harnesses, profiles, tui_state

LOOP_PHASES: tuple[str, ...] = ("review", "triage", "remediation", "checks", "commit")
PHASE_ENABLED_GLYPH = "[ok]"
PHASE_DISABLED_GLYPH = "[ ]"
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
        return "none"
    if isinstance(value, int | float):
        return f"{value:g}s"
    return f"{value}s"


def _phase_map(profile: profiles.Profile) -> dict[str, tui_state.PhaseView]:
    return {phase.name: phase for phase in tui_state.pipeline_phases(profile)}


def loop_header_text(source: Any) -> str:
    profile = _profile(source)
    max_iterations = _effective_int(
        source, LOOP_META_DOTTED["max_iterations"], profile.pipeline.max_iterations
    )
    inner_retries = _effective_int(
        source, LOOP_META_DOTTED["inner_check_retries"], profile.runtime.inner_check_retries
    )
    final_review = _effective_bool(
        source, LOOP_META_DOTTED["final_review"], profile.pipeline.final_review
    )
    final_text = "final review on" if final_review else "final review off"
    dirty = " *" if bool(getattr(source, "is_dirty", False)) else ""
    return (
        f"{profile.name}{dirty} · base {profile.pipeline.base} · max {max_iterations} · "
        f"inner retries {inner_retries} · {final_text}"
    )


def loop_rail_meta(source: Any) -> LoopRailMeta:
    profile = _profile(source)
    max_iterations = _effective_int(
        source, LOOP_META_DOTTED["max_iterations"], profile.pipeline.max_iterations
    )
    inner_retries = _effective_int(
        source, LOOP_META_DOTTED["inner_check_retries"], profile.runtime.inner_check_retries
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
    if phase == "remediation" and rail_meta.inner_rail:
        return "│ inner retry ↘"
    if phase == "checks" and rail_meta.inner_rail:
        return "│ inner retry ↗"
    if phase == "commit" and rail_meta.final_review:
        return "│ final review after loop"
    return "│"


def phase_card_lines(
    source: Any, phase_name: str, *, focused: bool, expanded: bool
) -> tuple[str, ...]:
    profile = _profile(source)
    phases = _phase_map(profile)
    phase = phases[phase_name]
    dotted = PHASE_DOTTED[phase_name]
    enabled = _effective_bool(source, dotted.get("enabled", ""), phase.enabled) if dotted.get("enabled") else phase.enabled
    harness = _effective_value(source, dotted.get("harness", ""), phase.harness)
    model = _effective_value(source, dotted.get("model", ""), phase.model)
    effort = _effective_value(source, dotted.get("effort", ""), phase.reasoning_effort)
    timeout = _effective_value(source, dotted.get("timeout", ""), phase.timeout_seconds)
    marker = PHASE_ENABLED_GLYPH if enabled else PHASE_DISABLED_GLYPH
    arrow = "▾" if expanded else "▸"
    focus = ">" if focused else " "
    if phase_name == "checks":
        commands = phase.command_count or 0
        summary = f"{focus}{arrow} {marker} checks · {commands} commands"
        if not expanded:
            return (summary,)
        return (summary, f"  commands: {commands} commands")
    summary_parts = [str(harness or "-")]
    if model:
        summary_parts.append(str(model))
    effort_text = harnesses.phase_effort_text(
        str(harness) if harness else None, str(effort) if effort else None
    )
    if effort_text:
        summary_parts.append(effort_text)
    summary_parts.append(_format_timeout(timeout))
    summary = f"{focus}{arrow} {marker} {phase_name} · " + " · ".join(summary_parts)
    if not expanded:
        return (summary,)
    lines = [
        summary,
        f"  harness: {harness or '-'}",
        f"  model: {model or '<default>'}",
        f"  effort: {effort or '<default>'}",
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


def triage_routes_lines(source: Any) -> tuple[str, ...]:
    profile = _profile(source)
    if not profile.triage.routing.enabled:
        return ()
    routing = profile.triage.routing
    lines = [
        "routing: "
        f"default {routing.default_route} · strict {routing.strict_on_unavailable_route} · "
        f"escalate {routing.allow_model_escalation}"
    ]
    for name, route in sorted(profile.triage.routes.items()):
        prefix = f"triage.routes.{name}"
        harness = _effective_value(source, f"{prefix}.harness", route.harness)
        model = _effective_value(source, f"{prefix}.model", route.model)
        effort = _effective_value(source, f"{prefix}.reasoning_effort", route.reasoning_effort)
        timeout = _effective_value(source, f"{prefix}.timeout_seconds", route.timeout_seconds)
        sandbox = _effective_value(source, f"{prefix}.sandbox", route.sandbox)
        fallback = _effective_value(source, f"{prefix}.fallback", route.fallback)
        effort_text = harnesses.phase_effort_text(
            str(harness) if harness else None, str(effort) if effort else None
        )
        lines.append(
            f"{name}: {harness} · {model or '<default>'} · {effort_text or '<default>'} · "
            f"{_format_timeout(timeout)} · {sandbox} · fallback {fallback or 'drop'}"
        )
    return tuple(lines)
