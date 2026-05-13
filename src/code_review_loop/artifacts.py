"""Artifact writing helpers with canonical JSON and path-safety checks."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

JSON_SCHEMA_VERSION = "1.0"


class ArtifactPathError(ValueError):
    """Raised when an artifact path would escape its run directory."""


def safe_artifact_path(run_dir: Path, relative_path: str | Path) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise ArtifactPathError("artifact path must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactPathError("artifact path must not contain empty, current, or parent parts")

    root = run_dir.resolve()
    target = run_dir / path
    parent = target.parent
    resolved_parent = parent.resolve(strict=False)
    if not resolved_parent.is_relative_to(root):
        raise ArtifactPathError("artifact path resolves outside the run directory")
    parent.mkdir(parents=True, exist_ok=True)
    return target


def write_text_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, content.encode("utf-8"))


def write_json_artifact(
    run_dir: Path,
    relative_path: str | Path,
    payload: Mapping[str, Any],
    *,
    schema_version: str = JSON_SCHEMA_VERSION,
) -> Path:
    target = safe_artifact_path(run_dir, relative_path)
    serializable = canonicalize_json({**dict(payload), "schema_version": schema_version})
    content = json.dumps(serializable, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(target, content.encode("utf-8"))
    return target


def canonicalize_json(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(canonicalize_json(key)): canonicalize_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [canonicalize_json(item) for item in value]
    return value


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with suppress(FileNotFoundError):
            tmp_path.unlink()
        raise
