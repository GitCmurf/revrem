from __future__ import annotations

import json

from code_review_loop.cli.commands import stats


def test_stats_models_aggregates_local_summary(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"model_invocations": [
        {"phase": "review", "harness": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "high", "duration_seconds": 12.0, "outcome": "ok", "tokens": 42},
        {"phase": "review", "harness": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "high", "duration_seconds": 18.0, "outcome": "error", "tokens": None},
    ]}), encoding="utf-8")
    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"cwd": str(repo), "summary_path": str(summary)}) + "\n", encoding="utf-8")

    assert stats.main(["models", "--repo", str(repo), "--format", "json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["calls"] == 2
    assert row["ok"] == 1
    assert row["token_coverage"] == "1/2"
    assert row["duration_seconds"]["mean"] == 15.0
    assert row["duration_seconds"]["p95"] == 18.0


def test_stats_models_includes_runs_from_repo_subdirectory(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    subdir = repo / "sub"
    subdir.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "model_invocations": [
                    {"phase": "review", "harness": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "high", "duration_seconds": 12.0, "outcome": "error", "tokens": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(
        json.dumps({"cwd": str(subdir), "summary_path": str(summary)}) + "\n",
        encoding="utf-8",
    )

    assert stats.main(["models", "--repo", str(subdir), "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["calls"] == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["phase"] == "review"
