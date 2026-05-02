"""Append-only run history for RevRem."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HISTORY_SCHEMA_VERSION = "1.0"
APP_DIR_NAME = "revrem"
HISTORY_FILE_NAME = "runs.jsonl"


def data_home(home: Path | None = None) -> Path:
    """Return the user data directory for RevRem history."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / APP_DIR_NAME
    root = home if home is not None else Path(os.environ.get("HOME", "~")).expanduser()
    return root / ".local" / "share" / APP_DIR_NAME


def default_history_path(home: Path | None = None) -> Path:
    return data_home(home) / HISTORY_FILE_NAME


def history_record(summary: dict[str, Any], *, cwd: Path) -> dict[str, Any]:
    """Build the small, stable JSONL record stored outside per-run artifacts."""
    iterations = summary.get("iterations")
    if not isinstance(iterations, list):
        iterations = []
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "run_id": summary.get("run_id"),
        "started_at": summary.get("started_at"),
        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "cwd": str(cwd),
        "base": summary.get("base"),
        "profile": summary.get("profile"),
        "final_status": summary.get("final_status"),
        "stopped_reason": summary.get("stopped_reason"),
        "max_iterations": summary.get("max_iterations"),
        "iteration_count": len(iterations),
        "pending_check_failures": bool(summary.get("pending_check_failures")),
        "artifact_dir": summary.get("artifact_dir"),
        "summary_path": (
            summary.get("artifact_paths", {}).get("summary")
            if isinstance(summary.get("artifact_paths"), dict)
            else None
        ),
    }


def append_history(summary: dict[str, Any], *, cwd: Path, path: Path | None = None) -> Path:
    """Append one run record as JSONL and return the history path."""
    target = path or default_history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    record = history_record(summary, cwd=cwd)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return target


def read_history(path: Path | None = None, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read history records newest-first."""
    target = path or default_history_path()
    if not target.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    records.reverse()
    if limit is not None:
        return records[:limit]
    return records
