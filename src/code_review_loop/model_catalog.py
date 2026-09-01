"""Layered harness and model capability catalog.

The catalog owns rapidly changing provider metadata. Command construction stays
in the audited harness adapters: catalog files may select a known driver, but
cannot inject argv templates or executable code.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from code_review_loop.repo_roots import repo_root_or_cwd

KNOWN_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
IMPLEMENTED_CATALOG_DRIVERS = ("codex", "claude", "gemini", "opencode", "kilo")
CATALOG_FILENAME = ".revrem-catalog.toml"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    harness: str
    efforts: tuple[str, ...] = ()
    default_effort: str | None = None
    capability_rank: int | None = None
    source: str = "packaged"


@dataclass(frozen=True)
class HarnessCatalogSpec:
    name: str
    driver: str
    executable: str
    source: str = "packaged"


@dataclass(frozen=True)
class Catalog:
    models: dict[tuple[str, str], ModelSpec]
    harnesses: dict[str, HarnessCatalogSpec]

    def model(self, harness: str, model: str | None) -> ModelSpec | None:
        if not model:
            return None
        direct = self.models.get((harness, model))
        if direct is not None:
            return direct
        harness_spec = self.harnesses.get(harness)
        if harness_spec is None:
            return None
        return self.models.get((harness_spec.driver, model))

    def models_for(self, harness: str | None = None) -> tuple[ModelSpec, ...]:
        values = list(self.models.values())
        if harness:
            catalog_spec = self.harnesses.get(harness)
            if catalog_spec is not None:
                values = [
                    item
                    for item in values
                    if item.harness in {harness, catalog_spec.driver}
                ]
            else:
                values = [item for item in values if item.harness == harness]
        return tuple(sorted(values, key=lambda item: (item.harness, -(item.capability_rank or 0), item.id)))


def load_catalog(cwd: Path | None = None, *, home: Path | None = None) -> Catalog:
    """Load catalog layers from least to most specific.

    Project catalogs are resolved from the repository root so subdirectory
    invocations still pick up `.revrem-catalog.toml`.
    """
    root = repo_root_or_cwd((cwd or Path.cwd()).resolve())
    user_home = (home or Path.home()).resolve()
    codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex")).resolve()
    source_paths = (
        codex_home / "models_cache.json",
        user_home / ".config" / "revrem" / "catalog.toml",
        root / CATALOG_FILENAME,
    )
    signatures = tuple(_source_signature(path) for path in source_paths)
    return _load_catalog_cached(root, user_home, codex_home, signatures)


@lru_cache(maxsize=32)
def _load_catalog_cached(
    root: Path,
    user_home: Path,
    codex_home: Path,
    _signatures: tuple[tuple[str, int, int] | None, ...],
) -> Catalog:
    """Parse immutable catalog layers once for each observed source version."""
    layers: list[tuple[str, dict[str, Any]]] = []
    packaged = files("code_review_loop").joinpath("catalog.toml").read_bytes()
    layers.append(("packaged", tomllib.loads(packaged.decode("utf-8"))))
    cache = codex_home / "models_cache.json"
    if cache.is_file():
        layers.append((str(cache), _codex_cache_layer(cache)))
    user = user_home / ".config" / "revrem" / "catalog.toml"
    if user.is_file():
        layers.append((str(user), _read_toml(user)))
    project = root / CATALOG_FILENAME
    if project.is_file():
        layers.append((str(project), _read_toml(project)))

    models: dict[tuple[str, str], ModelSpec] = {}
    harness_specs: dict[str, HarnessCatalogSpec] = {}
    for source, raw in layers:
        for entry in raw.get("harness", []):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"catalog harness entry in {source} is missing required field 'name'"
                )
            driver = str(entry.get("driver", name))
            if driver not in IMPLEMENTED_CATALOG_DRIVERS:
                raise ValueError(f"catalog harness {name!r} selects unknown built-in driver {driver!r}")
            harness_specs[name] = HarnessCatalogSpec(
                name=name,
                driver=driver,
                executable=str(entry.get("executable", name)),
                source=source,
            )
        for entry in raw.get("model", []):
            if not isinstance(entry, dict):
                continue
            harness = str(entry.get("harness", "codex"))
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id:
                raise ValueError(
                    f"catalog model entry in {source} is missing required field 'id'"
                )
            previous = models.get((harness, model_id))
            effort_values = entry.get("efforts", previous.efforts if previous else ())
            if not isinstance(effort_values, (list, tuple)):
                raise ValueError(
                    f"catalog model {model_id!r} in {source} field 'efforts' must be a list or tuple"
                )
            efforts = tuple(str(value) for value in effort_values)
            default = entry.get("default_effort", previous.default_effort if previous else None)
            rank = entry.get("capability_rank", previous.capability_rank if previous else None)
            models[(harness, model_id)] = ModelSpec(
                id=model_id,
                harness=harness,
                efforts=efforts,
                default_effort=str(default) if default is not None else None,
                capability_rank=int(rank) if rank is not None else None,
                source=source,
            )
    return Catalog(models=models, harnesses=harness_specs)


def _source_signature(path: Path) -> tuple[str, int, int] | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    return (str(path), stat_result.st_mtime_ns, stat_result.st_size)


def validate_selection(
    harness: str, model: str | None, effort: str | None, *, cwd: Path | None = None
) -> str | None:
    """Reject known-invalid pairs; return a warning for unknown metadata."""
    if effort is not None and effort not in KNOWN_EFFORTS:
        raise ValueError(
            f"reasoning effort {effort!r} is not one of: {', '.join(KNOWN_EFFORTS)}"
        )
    if not model or not effort:
        return None
    spec = load_catalog(cwd).model(harness, model)
    if spec is None:
        return f"model {model!r} is not in the local {harness} catalog; passing it through"
    if spec.efforts and effort not in spec.efforts:
        raise ValueError(
            f"reasoning effort {effort!r} is not supported by {harness} model {model!r}; "
            f"choose one of: {', '.join(spec.efforts)}"
        )
    return None


def effort_choices(harness: str, model: str | None, *, cwd: Path | None = None) -> tuple[str, ...]:
    spec = load_catalog(cwd).model(harness, model)
    return spec.efforts if spec and spec.efforts else KNOWN_EFFORTS


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _extract_codex_cache_reasoning_efforts(entry: dict[str, Any]) -> list[str] | None:
    effort_fields = (
        "supported_reasoning_levels",
        "supported_reasoning_efforts",
        "reasoning_efforts",
    )
    has_effort_field = any(name in entry for name in effort_fields)
    effort_source = next(
        (
            entry[name]
            for name in effort_fields
            if entry.get(name)
        ),
        None,
    )
    if not has_effort_field:
        return None
    if effort_source is None:
        return []
    if not isinstance(effort_source, (list, tuple)):
        return None
    efforts: list[str] = []
    for item in effort_source:
        value = item.get("effort") if isinstance(item, dict) else item
        if value:
            efforts.append(str(value))
    return efforts


def _codex_cache_layer(path: Path) -> dict[str, Any]:
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # Codex owns this optional cache and may be replacing it while RevRem
        # starts. Packaged metadata remains the safe, deterministic fallback.
        return {}
    if isinstance(raw, dict):
        entries = raw.get("models", [])
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = []
    if not isinstance(entries, list):
        return {}
    models: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("slug") or entry.get("id") or entry.get("model")
        if not model_id:
            continue
        model: dict[str, Any] = {
            "id": model_id,
            "harness": "codex",
        }
        efforts = _extract_codex_cache_reasoning_efforts(entry)
        if efforts is not None:
            model["efforts"] = efforts
        default_effort = (
            entry.get("default_reasoning_level")
            or entry.get("default_reasoning_effort")
            or entry.get("default_effort")
        )
        if default_effort is not None:
            model["default_effort"] = default_effort
        models.append(model)
    return {"model": models}
