"""Dependency-free view models for the optional RevRem TUI."""

from __future__ import annotations

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
class HomeSnapshot:
    cwd: str
    profiles: tuple[ProfileView, ...]
    recent_runs: tuple[dict[str, Any], ...]
    harnesses: tuple[HarnessView, ...]


def build_home_snapshot(
    *,
    cwd: Path,
    home: Path | None = None,
    history_limit: int = 5,
    history_path: Path | None = None,
) -> HomeSnapshot:
    return HomeSnapshot(
        cwd=str(cwd),
        profiles=tuple(profile_view(profile) for profile in profiles.list_profiles(cwd=cwd, home=home)),
        recent_runs=tuple(run_history.read_history(history_path, limit=history_limit)),
        harnesses=harness_views(),
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


def phase_view(name: str, enabled: bool, phase: profiles.PhaseConfig | profiles.TriageConfig) -> PhaseView:
    return PhaseView(
        name=name,
        enabled=enabled,
        harness=phase.harness,
        model=phase.model,
        reasoning_effort=phase.reasoning_effort,
        timeout_seconds=phase.timeout_seconds,
    )
