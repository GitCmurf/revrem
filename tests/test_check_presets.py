from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import check_presets


def _summary(path: Path, checks: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"resume_config": {"check_commands": checks}}),
        encoding="utf-8",
    )
    return path


def test_detect_check_presets_reports_repository_capabilities(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "dev-check").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\n[tool.mypy]\n", encoding="utf-8"
    )
    (tmp_path / "AGENTS.md").write_text(
        "<!-- MEMINIT_PROTOCOL: begin -->", encoding="utf-8"
    )

    presets = check_presets.detect_check_presets(tmp_path)

    assert presets[0].checks == ("./scripts/dev-check",)
    assert {preset.key for preset in presets} >= {
        "repo-gate",
        "python-fast",
        "python-static",
        "meminit",
        "diff-check",
    }


def test_recent_check_presets_are_repo_local_deduplicated_and_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    repo.mkdir()
    other.mkdir()
    (repo / ".git").mkdir()
    (other / ".git").mkdir()
    first = _summary(repo / "runs" / "one" / "summary.json", ["pytest -q"])
    duplicate = _summary(repo / "runs" / "two" / "summary.json", ["pytest -q"])
    third = _summary(repo / "runs" / "three" / "summary.json", ["ruff check ."])
    foreign = _summary(other / "runs" / "foreign" / "summary.json", ["make all"])
    records = [
        {"cwd": str(other), "summary_path": str(foreign), "profile": "x"},
        {"cwd": str(repo), "summary_path": str(first), "profile": "docs"},
        {"cwd": str(repo), "summary_path": str(duplicate), "profile": "docs"},
        {"cwd": str(repo), "summary_path": str(third), "profile": "security"},
    ]
    monkeypatch.setattr(
        check_presets.run_history,
        "read_history",
        lambda *, limit=None: records[:limit],
    )

    presets = check_presets.recent_check_presets(
        repo,
        result_limit=2,
        excluded=(("ruff check .",),),
    )

    assert [preset.checks for preset in presets] == [("pytest -q",)]
    assert presets[0].source == "recent"


def test_recent_check_presets_ignore_malformed_summaries(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(
        check_presets.run_history,
        "read_history",
        lambda *, limit=None: [{"cwd": str(tmp_path), "summary_path": str(summary)}],
    )

    assert check_presets.recent_check_presets(tmp_path) == ()


def test_recent_check_presets_filters_by_repository_before_history_limit(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    repo.mkdir()
    other.mkdir()
    (repo / ".git").mkdir()
    (other / ".git").mkdir()
    summary = _summary(repo / "runs" / "local" / "summary.json", ["pytest -q"])
    records = [
        {"cwd": str(other), "summary_path": str(other / f"summary-{index}.json")}
        for index in range(20)
    ] + [{"cwd": str(repo), "summary_path": str(summary)}]
    monkeypatch.setattr(
        check_presets.run_history,
        "read_history",
        lambda *, limit=None: records if limit is None else records[:limit],
    )

    presets = check_presets.recent_check_presets(repo, history_limit=20)

    assert [preset.checks for preset in presets] == [("pytest -q",)]
