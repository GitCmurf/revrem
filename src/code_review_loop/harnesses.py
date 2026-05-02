"""Harness metadata for review/remediation backends.

The loop only executes Codex today, but profiles should not bake Codex-specific
shape into user configuration. This registry keeps validation and future command
construction behind a small boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessSpec:
    name: str
    executable: str
    implemented: bool
    notes: str = ""


HARNESS_REGISTRY: dict[str, HarnessSpec] = {
    "codex": HarnessSpec(
        name="codex",
        executable="codex",
        implemented=True,
        notes="Implemented review/remediation backend.",
    ),
    "claude": HarnessSpec(
        name="claude",
        executable="claude",
        implemented=False,
        notes="Reserved for a future headless non-interactive Claude CLI adapter.",
    ),
    "gemini": HarnessSpec(
        name="gemini",
        executable="gemini",
        implemented=False,
        notes="Reserved for a future headless non-interactive Gemini CLI adapter.",
    ),
    "opencode": HarnessSpec(
        name="opencode",
        executable="opencode",
        implemented=False,
        notes="Reserved for a future headless non-interactive opencode adapter.",
    ),
    "kilo": HarnessSpec(
        name="kilo",
        executable="kilo",
        implemented=False,
        notes="Reserved for a future headless non-interactive Kilo adapter.",
    ),
}


def known_harness_names() -> tuple[str, ...]:
    return tuple(HARNESS_REGISTRY)


def validate_harness_name(name: str, *, field: str) -> None:
    if name not in HARNESS_REGISTRY:
        known = ", ".join(known_harness_names())
        raise ValueError(f"{field} must be one of: {known}")


def require_implemented_harness(name: str, *, field: str) -> None:
    validate_harness_name(name, field=field)
    spec = HARNESS_REGISTRY[name]
    if not spec.implemented:
        raise ValueError(
            f"{field}={name!r} is valid profile syntax, but only the codex backend is implemented"
        )
