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
