"""Dependency-free view models for the optional RevRem TUI."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_review_loop import events as event_model
from code_review_loop import harnesses, profiles, run_history


@dataclass(frozen=True)
class HarnessView:
    name: str
    executable: str
    implemented: bool
    notes: str


@dataclass(frozen=True)
class ProfileView:
    name: str
    description: str
    source: str | None
    base: str
    max_iterations: int
    checks: tuple[str, ...]


@dataclass(frozen=True)
class PhaseView:
    name: str
    enabled: bool
    harness: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    command_count: int | None = None


@dataclass(frozen=True)
class RunPreview:
    profile_name: str
    argv: tuple[str, ...]
    shell_command: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactLinkView:
    kind: str
    path: str
    exists: bool


@dataclass(frozen=True)
class RunEventView:
    seq: int
    kind: str
    phase: str | None
    iteration: int | str | None
    detail: str


@dataclass(frozen=True)
class RunMonitorView:
    run_id: str
    final_status: str
    stopped_reason: str | None
    artifact_dir: str | None
    artifacts: tuple[ArtifactLinkView, ...]
    events: tuple[RunEventView, ...] = ()
    events_truncated: bool = False
    event_error: str | None = None


@dataclass(frozen=True)
class LaunchPlan:
    profile_name: str
    mode: str
    argv: tuple[str, ...]
    shell_command: str


@dataclass(frozen=True)
class TuiScreen:
    name: str
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TuiShellModel:
    snapshot: HomeSnapshot
    selected_profile_name: str | None
    selected_launch_plan: LaunchPlan | None
    screens: tuple[TuiScreen, ...]


@dataclass(frozen=True)
class HomeSnapshot:
    cwd: str
    profiles: tuple[ProfileView, ...]
    recent_runs: tuple[dict[str, Any], ...]
    harnesses: tuple[HarnessView, ...]
    run_previews: tuple[RunPreview, ...]
    run_monitors: tuple[RunMonitorView, ...]


def build_home_snapshot(
    *,
    cwd: Path,
    home: Path | None = None,
    history_limit: int = 5,
    history_path: Path | None = None,
) -> HomeSnapshot:
    resolved_profiles = tuple(profiles.resolve_profiles(cwd=cwd, home=home, require_implemented=False))
    return home_snapshot_for_profiles(
        cwd=cwd,
        resolved_profiles=resolved_profiles,
        history_limit=history_limit,
        history_path=history_path,
    )


def home_snapshot_for_profiles(
    *,
    cwd: Path,
    resolved_profiles: tuple[profiles.Profile, ...],
    history_limit: int = 5,
    history_path: Path | None = None,
) -> HomeSnapshot:
    recent_runs = tuple(run_history.read_history(history_path, limit=history_limit))
    return HomeSnapshot(
        cwd=str(cwd),
        profiles=tuple(profile_view(profile) for profile in resolved_profiles),
        recent_runs=recent_runs,
        harnesses=harness_views(),
        run_previews=tuple(run_preview(profile) for profile in resolved_profiles),
        run_monitors=tuple(
            run_monitor_view(record)
            for record in recent_runs
        ),
    )


def build_shell_model(
    *,
    cwd: Path,
    home: Path | None = None,
    history_limit: int = 5,
    history_path: Path | None = None,
    selected_profile_name: str | None = None,
) -> TuiShellModel:
    resolved_profiles = tuple(profiles.resolve_profiles(cwd=cwd, home=home, require_implemented=False))
    snapshot = home_snapshot_for_profiles(
        cwd=cwd,
        resolved_profiles=resolved_profiles,
        history_limit=history_limit,
        history_path=history_path,
    )
    selected_profile = _select_profile(resolved_profiles, selected_profile_name)
    plan = launch_plan(selected_profile, dry_run=True) if selected_profile is not None else None
    return TuiShellModel(
        snapshot=snapshot,
        selected_profile_name=selected_profile.name if selected_profile is not None else None,
        selected_launch_plan=plan,
        screens=(
            home_screen(snapshot, selected_profile_name=selected_profile.name if selected_profile else None),
            profiles_screen(snapshot),
            pipeline_screen(snapshot, selected_profile),
            run_monitor_screen(snapshot),
            actions_screen(selected_profile.name if selected_profile else None),
        ),
    )


def _select_profile(
    resolved_profiles: tuple[profiles.Profile, ...],
    selected_profile_name: str | None = None,
) -> profiles.Profile | None:
    if not resolved_profiles:
        if selected_profile_name is not None:
            raise FileNotFoundError(f"profile not found: {selected_profile_name}")
        return None
    if selected_profile_name is not None:
        for profile in resolved_profiles:
            if profile.name == selected_profile_name:
                return profile
        raise FileNotFoundError(f"profile not found: {selected_profile_name}")
    return resolved_profiles[0]


def home_screen(snapshot: HomeSnapshot, *, selected_profile_name: str | None = None) -> TuiScreen:
    implemented = ", ".join(h.name for h in snapshot.harnesses if h.implemented) or "none"
    reserved = ", ".join(h.name for h in snapshot.harnesses if not h.implemented) or "none"
    lines = [
        f"Workspace: {snapshot.cwd}",
        f"Selected profile: {selected_profile_name or 'none'}",
        f"Profiles: {len(snapshot.profiles)} available",
        f"Recent runs: {len(snapshot.recent_runs)} loaded",
        f"Artifact links: {sum(len(run.artifacts) for run in snapshot.run_monitors)} indexed",
        f"Implemented harnesses: {implemented}",
        f"Reserved harnesses: {reserved}",
    ]
    if snapshot.run_previews:
        lines.append(f"Quick start: {snapshot.run_previews[0].shell_command}")
    else:
        lines.append("Quick start: revrem config new final-pr")
    lines.append(
        "Keys: d dry-run, s show, e edit, n new, c clone, x export, i import, delete delete, q quit."
    )
    return TuiScreen(name="home", title="Home", lines=tuple(lines))


def profiles_screen(snapshot: HomeSnapshot) -> TuiScreen:
    lines: list[str] = ["Name | Description | Base | Max | Checks | Source"]
    if not snapshot.profiles:
        lines.append("No profiles found. Create one with revrem config new final-pr.")
    for profile in snapshot.profiles:
        lines.append(
            f"{profile.name} | {profile.description or '-'} | {profile.base} | "
            f"{profile.max_iterations} | {len(profile.checks)} | {profile.source or '-'}"
        )
    lines.append("Actions: New, Edit, Clone, Delete, Export, and Import shell through revrem config.")
    return TuiScreen(name="profiles", title="Profiles", lines=tuple(lines))


def pipeline_screen(snapshot: HomeSnapshot, selected_profile: profiles.Profile | None) -> TuiScreen:
    if selected_profile is None:
        return TuiScreen(
            name="pipeline",
            title="Pipeline",
            lines=("No selected profile.",),
        )
    lines = [f"Profile: {selected_profile.name}"]
    for phase in pipeline_phases(selected_profile):
        state = "enabled" if phase.enabled else "disabled"
        details = [state]
        if phase.harness:
            details.append(f"harness={phase.harness}")
        if phase.model:
            details.append(f"model={phase.model}")
        if phase.reasoning_effort:
            details.append(f"effort={phase.reasoning_effort}")
        if phase.timeout_seconds is not None:
            details.append(f"timeout={phase.timeout_seconds:g}s")
        if phase.command_count is not None:
            details.append(f"commands={phase.command_count}")
        lines.append(f"{phase.name}: " + ", ".join(details))
    plan = launch_plan(selected_profile, dry_run=True)
    lines.append(f"Dry-run launch: {plan.shell_command}")
    return TuiScreen(name="pipeline", title="Pipeline", lines=tuple(lines))


def run_monitor_screen(snapshot: HomeSnapshot) -> TuiScreen:
    lines: list[str] = []
    if not snapshot.run_monitors:
        lines.append("No recent runs found.")
    for monitor in snapshot.run_monitors:
        reason = f" ({monitor.stopped_reason})" if monitor.stopped_reason else ""
        lines.append(f"{monitor.run_id or '<unknown>'}: {monitor.final_status}{reason}")
        if monitor.artifact_dir:
            lines.append(f"  artifacts: {monitor.artifact_dir}")
        for artifact in monitor.artifacts[:6]:
            exists = "exists" if artifact.exists else "missing"
            lines.append(f"  {artifact.kind}: {artifact.path} [{exists}]")
        if len(monitor.artifacts) > 6:
            lines.append(f"  ... {len(monitor.artifacts) - 6} more artifact links")
        if monitor.event_error:
            lines.append(f"  events: unavailable ({monitor.event_error})")
        elif monitor.events:
            suffix = " [truncated]" if monitor.events_truncated else ""
            lines.append(f"  events: {len(monitor.events)} loaded{suffix}")
            for event in monitor.events[-4:]:
                phase = event.phase or event.kind
                iteration = "" if event.iteration is None else f"|{event.iteration}"
                detail = f": {event.detail}" if event.detail else ""
                lines.append(f"    {event.seq:04d}|{phase}{iteration}|{event.kind}{detail}")
    return TuiScreen(name="run-monitor", title="Run Monitor", lines=tuple(lines))


def actions_screen(selected_profile_name: str | None) -> TuiScreen:
    selected = selected_profile_name or "<none>"
    return TuiScreen(
        name="actions",
        title="Actions",
        lines=(
            f"Selected profile: {selected}",
            "Profile name field: target for New, Clone, Delete, Show, Edit, Export, and Dry run.",
            "Path field: source path for Import; optional destination context for future export workflows.",
            "Actions use revrem config commands so validation, atomic writes, and error handling stay shared.",
        ),
    )


def render_shell_text(model: TuiShellModel) -> str:
    sections: list[str] = []
    for screen in model.screens:
        escaped_lines = "\n".join(markup_escape(line) for line in screen.lines)
        sections.append(f"[b]{markup_escape(screen.title)}[/b]\n{escaped_lines}")
    return "\n\n".join(sections)


def markup_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def harness_views() -> tuple[HarnessView, ...]:
    return tuple(
        HarnessView(
            name=spec.name,
            executable=spec.executable,
            implemented=spec.implemented,
            notes=spec.notes,
        )
        for spec in harnesses.HARNESS_REGISTRY.values()
    )


def profile_view(profile: profiles.Profile) -> ProfileView:
    return ProfileView(
        name=profile.name,
        description=profile.description,
        source=profile.source,
        base=profile.pipeline.base,
        max_iterations=profile.pipeline.max_iterations,
        checks=profile.pipeline.checks,
    )


def pipeline_phases(profile: profiles.Profile) -> tuple[PhaseView, ...]:
    phases = [
        phase_view("review", True, profile.review),
        phase_view("triage", profile.triage.enabled, profile.triage),
        phase_view("remediation", True, profile.remediation),
        PhaseView("checks", bool(profile.pipeline.checks), command_count=len(profile.pipeline.checks)),
        PhaseView("commit", profile.commit.enabled, model=profile.commit.message_model),
    ]
    return tuple(phases)


def run_preview(profile: profiles.Profile) -> RunPreview:
    argv = ["revrem", "--profile", profile.name]
    return RunPreview(
        profile_name=profile.name,
        argv=tuple(argv),
        shell_command=shlex.join(argv),
        checks=profile.pipeline.checks,
    )


def launch_plan(profile: profiles.Profile, *, dry_run: bool = True) -> LaunchPlan:
    preview = run_preview(profile)
    argv = list(preview.argv)
    mode = "dry-run" if dry_run else "run"
    if dry_run:
        argv.append("--dry-run")
    return LaunchPlan(
        profile_name=profile.name,
        mode=mode,
        argv=tuple(argv),
        shell_command=shlex.join(argv),
    )


def edit_plan(profile: profiles.Profile) -> LaunchPlan:
    return edit_plan_for_name(profile.name)


def edit_plan_for_name(profile_name: str) -> LaunchPlan:
    argv = ("revrem", "config", "edit", profile_name)
    return LaunchPlan(
        profile_name=profile_name,
        mode="edit",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def show_plan_for_name(profile_name: str) -> LaunchPlan:
    argv = ("revrem", "config", "show", profile_name)
    return LaunchPlan(
        profile_name=profile_name,
        mode="show",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def new_plan_for_name(profile_name: str) -> LaunchPlan:
    argv = ("revrem", "config", "new", profile_name, "--no-interactive")
    return LaunchPlan(
        profile_name=profile_name,
        mode="new",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def clone_plan_for_name(source_name: str, target_name: str) -> LaunchPlan:
    argv = ("revrem", "config", "clone", source_name, target_name)
    return LaunchPlan(
        profile_name=target_name,
        mode="clone",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def delete_plan_for_name(profile_name: str) -> LaunchPlan:
    argv = ("revrem", "config", "delete", profile_name, "--yes")
    return LaunchPlan(
        profile_name=profile_name,
        mode="delete",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def export_plan_for_name(profile_name: str) -> LaunchPlan:
    argv = ("revrem", "config", "export", profile_name)
    return LaunchPlan(
        profile_name=profile_name,
        mode="export",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def import_plan_for_path(path: str) -> LaunchPlan:
    argv = ("revrem", "config", "import", path)
    return LaunchPlan(
        profile_name=Path(path).stem or "import",
        mode="import",
        argv=argv,
        shell_command=shlex.join(argv),
    )


def run_monitor_view(record: dict[str, Any]) -> RunMonitorView:
    artifact_dir = record.get("artifact_dir")
    artifact_paths = record.get("artifact_paths")
    record_cwd = record.get("cwd")
    artifacts: list[ArtifactLinkView] = []
    if isinstance(artifact_paths, dict):
        for kind, value in artifact_paths.items():
            if kind == "artifact_dir":
                continue
            if isinstance(value, str):
                artifacts.append(artifact_link_view(kind, value, record_cwd=record_cwd))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        artifacts.append(artifact_link_view(kind, item, record_cwd=record_cwd))
    event_views, events_truncated, event_error = run_event_views(record)
    return RunMonitorView(
        run_id=str(record.get("run_id") or ""),
        final_status=str(record.get("final_status") or "unknown"),
        stopped_reason=(
            str(record["stopped_reason"])
            if isinstance(record.get("stopped_reason"), str)
            else None
        ),
        artifact_dir=str(artifact_dir) if isinstance(artifact_dir, str) else None,
        artifacts=tuple(artifacts),
        events=event_views,
        events_truncated=events_truncated,
        event_error=event_error,
    )


def artifact_link_view(kind: str, path: str, *, record_cwd: str | None = None) -> ArtifactLinkView:
    resolved_path = resolve_record_path(path, record_cwd=record_cwd)
    return ArtifactLinkView(kind=kind, path=path, exists=resolved_path.exists())


def run_event_views(record: dict[str, Any]) -> tuple[tuple[RunEventView, ...], bool, str | None]:
    events_path = events_path_for_record(record)
    if events_path is None or not events_path.is_file():
        return (), False, None
    try:
        records, truncated = event_model.read_events(events_path)
    except (ValueError, OSError) as exc:
        return (), False, str(exc)
    return tuple(run_event_view(event) for event in records), truncated, None


def events_path_for_record(record: dict[str, Any]) -> Path | None:
    record_cwd = record.get("cwd")
    artifact_dir = record.get("artifact_dir")
    artifact_paths = record.get("artifact_paths")
    if not isinstance(artifact_dir, str) and isinstance(artifact_paths, dict):
        artifact_dir_value = artifact_paths.get("artifact_dir")
        if isinstance(artifact_dir_value, str):
            artifact_dir = artifact_dir_value
    if not isinstance(artifact_dir, str):
        return None
    return resolve_record_path(artifact_dir, record_cwd=record_cwd) / event_model.EVENTS_FILENAME


def run_event_view(event: event_model.Event) -> RunEventView:
    return RunEventView(
        seq=event.seq,
        kind=event.kind,
        phase=event.phase,
        iteration=event.iteration,
        detail=event_detail(event),
    )


def event_detail(event: event_model.Event) -> str:
    for key in ("status", "reason", "message", "summary", "path"):
        value = event.payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def resolve_record_path(path: str, *, record_cwd: object) -> Path:
    resolved_path = Path(path)
    if not resolved_path.is_absolute() and isinstance(record_cwd, str):
        return Path(record_cwd) / resolved_path
    return resolved_path


def phase_view(name: str, enabled: bool, phase: profiles.PhaseConfig | profiles.TriageConfig) -> PhaseView:
    return PhaseView(
        name=name,
        enabled=enabled,
        harness=phase.harness,
        model=phase.model,
        reasoning_effort=phase.reasoning_effort,
        timeout_seconds=phase.timeout_seconds,
    )
