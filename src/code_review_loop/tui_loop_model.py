"""Pure working-copy model for the editable TUI loop screen."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    raw = asdict(profile)
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

    @classmethod
    def load(cls, name: str, *, cwd: Path, home: Path | None = None) -> LoopEditModel:
        profile = profiles.resolve_profile(
            name, cwd=cwd, home=home, require_implemented=False
        )
        return cls(name=name, profile=profile, cwd=cwd, home=home)

    @property
    def is_dirty(self) -> bool:
        return bool(self.edits)

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

    def save(self) -> Path:
        path = profiles.save_profile_raw(
            self.name, self.authored_delta(), cwd=self.cwd, home=self.home
        )
        self.edits.clear()
        self.profile = profiles.resolve_profile(
            self.name, cwd=self.cwd, home=self.home, require_implemented=False
        )
        return path


def _same_value(left: object, right: object) -> bool:
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return tuple(left) == tuple(right)
    return left == right
