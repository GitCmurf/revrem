"""Dependency-free view models for the optional RevRem TUI."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
class RunMonitorView:
    run_id: str
    final_status: str
    stopped_reason: str | None
    artifact_dir: str | None
    artifacts: tuple[ArtifactLinkView, ...]


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
    profile_list = tuple(profiles.list_profiles(cwd=cwd, home=home))
    resolved_profiles = tuple(
        profiles.resolve_profile(profile.name, cwd=cwd, home=home, require_implemented=False)
        for profile in profile_list
    )
    return HomeSnapshot(
        cwd=str(cwd),
        profiles=tuple(profile_view(profile) for profile in resolved_profiles),
        recent_runs=tuple(run_history.read_history(history_path, limit=history_limit)),
        harnesses=harness_views(),
        run_previews=tuple(run_preview(profile) for profile in resolved_profiles),
        run_monitors=tuple(
            run_monitor_view(record)
            for record in run_history.read_history(history_path, limit=history_limit)
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
    snapshot = build_home_snapshot(
        cwd=cwd,
        home=home,
        history_limit=history_limit,
        history_path=history_path,
    )
    selected_profile = _select_profile(cwd, home, snapshot, selected_profile_name)
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
        ),
    )


def _select_profile(
    cwd: Path,
    home: Path | None,
    snapshot: HomeSnapshot,
    selected_profile_name: str | None = None,
) -> profiles.Profile | None:
    profile_names = [profile.name for profile in snapshot.profiles]
    if not profile_names:
        if selected_profile_name is not None:
            raise FileNotFoundError(f"profile not found: {selected_profile_name}")
        return None
    if selected_profile_name is not None and selected_profile_name not in profile_names:
        raise FileNotFoundError(f"profile not found: {selected_profile_name}")
    wanted_name = selected_profile_name or profile_names[0]
    return profiles.resolve_profile(wanted_name, cwd=cwd, home=home, require_implemented=False)


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
    lines.append("Press d to launch a dry-run preview for the selected profile; q quits.")
    return TuiScreen(name="home", title="Home", lines=tuple(lines))


def profiles_screen(snapshot: HomeSnapshot) -> TuiScreen:
    lines: list[str] = []
    if not snapshot.profiles:
        lines.append("No profiles found. Create one with revrem config new final-pr.")
    for profile in snapshot.profiles:
        description = f" - {profile.description}" if profile.description else ""
        source = f" [{profile.source}]" if profile.source else ""
        lines.append(
            f"{profile.name}{description}{source} | base={profile.base} "
            f"max={profile.max_iterations} checks={len(profile.checks)}"
        )
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
    return TuiScreen(name="run-monitor", title="Run Monitor", lines=tuple(lines))


def render_shell_text(model: TuiShellModel) -> str:
    sections: list[str] = []
    for screen in model.screens:
        sections.append(f"[b]{screen.title}[/b]\n" + "\n".join(screen.lines))
    return "\n\n".join(sections)


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
    argv = [
        "revrem",
        "--profile",
        profile.name,
        "--base",
        profile.pipeline.base,
        "--max-iterations",
        str(profile.pipeline.max_iterations),
        "--summary-format",
        profile.output.summary_format,
    ]
    if profile.output.progress_style != "compact":
        argv.extend(["--progress-style", profile.output.progress_style])
    if profile.output.debug_status_detection:
        argv.append("--debug-status-detection")
    if profile.output.terminal_title:
        argv.append("--terminal-title")
    if profile.commit.enabled:
        argv.append("--commit-after-remediation")
    for check in profile.pipeline.checks:
        argv.extend(["--check", check])
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
    )


def artifact_link_view(kind: str, path: str, *, record_cwd: str | None = None) -> ArtifactLinkView:
    resolved_path = Path(path)
    if isinstance(record_cwd, str):
        resolved_path = Path(record_cwd) / resolved_path
    return ArtifactLinkView(kind=kind, path=path, exists=resolved_path.exists())


def phase_view(name: str, enabled: bool, phase: profiles.PhaseConfig | profiles.TriageConfig) -> PhaseView:
    return PhaseView(
        name=name,
        enabled=enabled,
        harness=phase.harness,
        model=phase.model,
        reasoning_effort=phase.reasoning_effort,
        timeout_seconds=phase.timeout_seconds,
    )
