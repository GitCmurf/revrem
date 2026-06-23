"""Bundled expert profile resources for RevRem."""

from __future__ import annotations

from importlib.resources import files

_PACKAGE = "code_review_loop.expert_profiles"


def list_builtin_profiles() -> list[str]:
    """Return bundled expert profile names in deterministic order."""
    root = files(_PACKAGE)
    return sorted(
        resource.name.removesuffix(".toml")
        for resource in root.iterdir()
        if resource.name.endswith(".toml")
    )


def load_builtin_profile(name: str) -> str:
    """Return the TOML text for a bundled expert profile.

    Uses ``importlib.resources`` so installed wheels and zip imports work the
    same as an editable checkout.
    """
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise FileNotFoundError(f"built-in profile not found: {name}")
    resource = files(_PACKAGE).joinpath(f"{name}.toml")
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, OSError) as exc:
        raise FileNotFoundError(f"built-in profile not found: {name}") from exc
