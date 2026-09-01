"""Pure working-copy model for the editable TUI loop screen."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path
from typing import Any

from code_review_loop import profiles


def _read_dotted(raw: dict[str, Any], dotted_key: str) -> Any:
    cursor: Any = raw
    for part in dotted_key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(dotted_key)
        cursor = cursor[part]
    return cursor


def _profile_to_raw(profile: profiles.Profile) -> dict[str, Any]:
    raw = profiles.profile_to_dict(profile)
    raw.pop("name", None)
    raw.pop("source", None)
    return raw


@dataclass
class LoopEditModel:
    """A resolved profile plus unsaved raw-profile edits."""

    name: str
    profile: profiles.Profile
    cwd: Path
    home: Path | None = None
    edits: dict[str, object] = field(default_factory=dict)
    replay_baseline: dict[str, object] = field(default_factory=dict)

    @classmethod
    def load(cls, name: str, *, cwd: Path, home: Path | None = None) -> LoopEditModel:
        profile = profiles.resolve_profile(
            name, cwd=cwd, home=home, require_implemented=False
        )
        return cls(name=name, profile=profile, cwd=cwd, home=home)

    @property
    def is_dirty(self) -> bool:
        return bool(self.edits)

    @property
    def is_user_modified(self) -> bool:
        return self.edits != self.replay_baseline

    def mark_replay_baseline(self) -> None:
        self.replay_baseline = dict(self.edits)

    def set_effective_profile(self, effective: profiles.Profile) -> None:
        """Represent a live effective profile as edits over this disk baseline."""
        baseline = _profile_to_raw(self.profile)
        effective_raw = _profile_to_raw(effective)
        self.edits = {
            dotted_key: value
            for dotted_key, value in _raw_differences(baseline, effective_raw).items()
        }

    def field_value(self, dotted_key: str, fallback: object) -> object:
        if dotted_key not in self.edits:
            return fallback
        value = self.edits[dotted_key]
        if value is None:
            return ""
        try:
            coerced = profiles.deep_set_raw({}, dotted_key, value)
        except ValueError:
            return value
        return _read_dotted(coerced, dotted_key)

    def set_field(self, dotted_key: str, value: object) -> None:
        try:
            coerced = profiles.deep_set_raw({}, dotted_key, value)
            proposed = _read_dotted(coerced, dotted_key)
        except ValueError:
            self.edits[dotted_key] = value
            return
        try:
            baseline = _read_dotted(_profile_to_raw(self.profile), dotted_key)
        except KeyError:
            self.edits[dotted_key] = value
            return
        if _same_value(proposed, baseline):
            self.edits.pop(dotted_key, None)
            return
        self.edits[dotted_key] = value

    def authored_delta(self) -> dict[str, object]:
        return reduce(
            lambda acc, item: profiles.deep_set_raw(acc, item[0], item[1]),
            self.edits.items(),
            {},
        )

    def effective_profile(self) -> profiles.Profile:
        """Return the validated resolved profile represented by this working copy."""
        raw = _profile_to_raw(self.profile)
        for dotted_key, value in self.edits.items():
            if value is None:
                _delete_dotted_raw(raw, dotted_key)
            else:
                raw = profiles.deep_set_raw(raw, dotted_key, value)
        return profiles.parse_profile(
            self.name,
            raw,
            source="tui-working-copy",
            catalog_cwd=self.cwd,
        )

    def save(self) -> Path:
        path = profiles.save_profile_raw(
            self.name, self.authored_delta(), cwd=self.cwd, home=self.home
        )
        self.edits.clear()
        self.replay_baseline.clear()
        self.profile = profiles.resolve_profile(
            self.name, cwd=self.cwd, home=self.home, require_implemented=False
        )
        return path


def _same_value(left: object, right: object) -> bool:
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return tuple(left) == tuple(right)
    return left == right


def _raw_differences(
    baseline: dict[str, Any], effective: dict[str, Any], prefix: str = ""
) -> dict[str, object]:
    differences: dict[str, object] = {}
    for key in sorted(baseline.keys() | effective.keys()):
        dotted_key = f"{prefix}.{key}" if prefix else key
        if key not in effective:
            differences[dotted_key] = None
            continue
        value = effective[key]
        if key not in baseline:
            differences[dotted_key] = value
            continue
        baseline_value = baseline[key]
        if isinstance(value, dict) and isinstance(baseline_value, dict):
            differences.update(_raw_differences(baseline_value, value, dotted_key))
        elif not _same_value(value, baseline_value):
            differences[dotted_key] = value
    return differences


def _delete_dotted_raw(raw: dict[str, Any], dotted_key: str) -> None:
    cursor: dict[str, Any] = raw
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        value = cursor.get(part)
        if not isinstance(value, dict):
            return
        cursor = value
    cursor.pop(parts[-1], None)
