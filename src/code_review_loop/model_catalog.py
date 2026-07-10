"""Layered harness and model capability catalog.

The catalog owns rapidly changing provider metadata. Command construction stays
in the audited harness adapters: catalog files may select a known driver, but
cannot inject argv templates or executable code.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

KNOWN_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
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
        return self.models.get((harness, model))

    def models_for(self, harness: str | None = None) -> tuple[ModelSpec, ...]:
        values = list(self.models.values())
        if harness:
            values = [item for item in values if item.harness == harness]
        return tuple(sorted(values, key=lambda item: (item.harness, -(item.capability_rank or 0), item.id)))


def load_catalog(cwd: Path | None = None, *, home: Path | None = None) -> Catalog:
    """Load catalog layers from least to most specific."""
    root = (cwd or Path.cwd()).resolve()
    user_home = home or Path.home()
    layers: list[tuple[str, dict[str, Any]]] = []
    packaged = files("code_review_loop").joinpath("catalog.toml").read_bytes()
    layers.append(("packaged", tomllib.loads(packaged.decode("utf-8"))))
    codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex"))
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
            name = str(entry["name"])
            driver = str(entry.get("driver", name))
            if driver not in {"codex", "claude", "gemini", "opencode", "kilo", "reserved"}:
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
            model_id = str(entry["id"])
            previous = models.get((harness, model_id))
            efforts = tuple(str(value) for value in entry.get("efforts", previous.efforts if previous else ()))
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


def validate_selection(harness: str, model: str | None, effort: str | None, *, cwd: Path | None = None) -> str | None:
    """Reject known-invalid pairs; return a warning for unknown metadata."""
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


def _codex_cache_layer(path: Path) -> dict[str, Any]:
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("models", raw if isinstance(raw, list) else [])
    models: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("slug") or entry.get("id") or entry.get("model")
        if not model_id:
            continue
        efforts_raw = (
            entry.get("supported_reasoning_levels")
            or entry.get("supported_reasoning_efforts")
            or entry.get("reasoning_efforts")
            or []
        )
        efforts = [item.get("effort") if isinstance(item, dict) else item for item in efforts_raw]
        model: dict[str, Any] = {
            "id": model_id,
            "harness": "codex",
        }
        if any(
            key in entry
            for key in (
                "supported_reasoning_levels",
                "supported_reasoning_efforts",
                "reasoning_efforts",
            )
        ):
            model["efforts"] = [str(item) for item in efforts if item]
        default_effort = (
            entry.get("default_reasoning_level")
            or entry.get("default_reasoning_effort")
            or entry.get("default_effort")
        )
        if default_effort is not None:
            model["default_effort"] = default_effort
        models.append(model)
    return {"model": models}
