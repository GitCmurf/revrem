"""Repository-aware verification-check choices shared by interactive clients."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Literal

from code_review_loop import run_history
from code_review_loop.repo_roots import repo_root_or_cwd


@dataclass(frozen=True)
class CheckPreset:
    key: str
    label: str
    checks: tuple[str, ...]
    source: Literal["detected", "recent"] = "detected"


def detect_check_presets(cwd: Path) -> tuple[CheckPreset, ...]:
    root = repo_root_or_cwd(cwd)
    presets: list[CheckPreset] = []
    if (root / "scripts" / "dev-check").is_file():
        presets.append(
            CheckPreset(
                "repo-gate",
                "repo gate: ./scripts/dev-check",
                ("./scripts/dev-check",),
            )
        )

    pyproject = root / "pyproject.toml"
    tests_dir = root / "tests"
    if pyproject.is_file() or tests_dir.is_dir():
        presets.append(
            CheckPreset("python-fast", "Python fast: pytest -q", ("pytest -q",))
        )

    static_checks: list[str] = []
    if pyproject.is_file():
        text = _read_text_best_effort(pyproject)
        if "[tool.ruff" in text or "ruff" in text:
            static_checks.append("ruff check .")
        if "[tool.mypy" in text or "mypy" in text:
            static_checks.append("mypy src")
    if static_checks:
        presets.append(
            CheckPreset(
                "python-static",
                "Python static: " + " && ".join(static_checks),
                tuple(static_checks),
            )
        )

    if _meminit_detected(root):
        presets.append(
            CheckPreset(
                "meminit",
                "Meminit DocOps: uv run --locked meminit check --format json",
                ("uv run --locked meminit check --format json",),
            )
        )
    presets.append(
        CheckPreset(
            "diff-check",
            "Git whitespace: git diff --check",
            ("git diff --check",),
        )
    )
    return tuple(presets)


def recent_check_presets(
    cwd: Path,
    *,
    history_limit: int = 20,
    result_limit: int = 5,
    excluded: tuple[tuple[str, ...], ...] = (),
) -> tuple[CheckPreset, ...]:
    root = repo_root_or_cwd(cwd)
    seen = set(excluded)
    results: list[CheckPreset] = []
    # History is shared across repositories. Select records for this repository
    # before bounding the candidate set, otherwise newer foreign runs can hide
    # its most recent presets.
    repository_records = (
        record
        for record in run_history.read_history()
        if isinstance(record.get("cwd"), str)
        and repo_root_or_cwd(Path(record["cwd"])) == root
    )
    for record in islice(repository_records, history_limit):
        record_cwd = record["cwd"]
        summary_path = record.get("summary_path")
        if not isinstance(summary_path, str) or not summary_path:
            continue
        path = Path(summary_path)
        if not path.is_absolute():
            path = Path(record_cwd) / path
        checks = _summary_checks(path)
        if not checks or checks in seen:
            continue
        seen.add(checks)
        digest = hashlib.sha256("\0".join(checks).encode()).hexdigest()[:12]
        profile = record.get("profile")
        finished = record.get("finished_at")
        context = " · ".join(
            str(value)
            for value in (profile, finished)
            if isinstance(value, str) and value
        )
        label = f"Recent: {context or path.parent.name} · {len(checks)} configured"
        results.append(CheckPreset(f"recent-{digest}", label, checks, source="recent"))
        if len(results) >= result_limit:
            break
    return tuple(results)


def _summary_checks(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    resume_config = payload.get("resume_config")
    if not isinstance(resume_config, dict):
        return ()
    checks = resume_config.get("check_commands")
    if not isinstance(checks, list) or not all(
        isinstance(item, str) for item in checks
    ):
        return ()
    return tuple(item for item in checks if item.strip())


def _read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _meminit_detected(cwd: Path) -> bool:
    if any(
        (cwd / name).exists()
        for name in ("docops.config.yaml", "meminit.toml", ".meminit")
    ):
        return True
    return "MEMINIT_PROTOCOL" in _read_text_best_effort(cwd / "AGENTS.md")
