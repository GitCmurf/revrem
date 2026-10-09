"""Pure view-models for the TUI profiles picker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_review_loop import profiles, tui_state


@dataclass(frozen=True)
class ProfilePickerRow:
    name: str
    group: str
    source_label: str
    summary: str
    description: str


def profile_picker_groups(snapshot: tui_state.HomeSnapshot) -> tuple[ProfilePickerRow, ...]:
    yours: list[ProfilePickerRow] = []
    presets: list[ProfilePickerRow] = []
    for profile in snapshot.profiles:
        source_label = _source_label(profile.source)
        group = "presets" if source_label == "builtin" else "yours"
        row = ProfilePickerRow(
            name=profile.name,
            group=group,
            source_label=source_label,
            summary=(
                f"base {profile.base} · max {profile.max_iterations} · "
                f"{len(profile.checks)} checks"
            ),
            description=profile.description or "",
        )
        (presets if group == "presets" else yours).append(row)
    yours.sort(key=lambda item: item.name)
    presets.sort(key=lambda item: item.name)
    return tuple(yours) + tuple(presets)


def _source_label(source: str | None) -> str:
    if not source:
        return "-"
    if source == profiles.BUILTIN_PROFILE_SOURCE:
        return "builtin"
    name = Path(source).name
    if name == ".revrem.toml":
        return "project"
    if name == "profiles.toml":
        return "user"
    return name or source
