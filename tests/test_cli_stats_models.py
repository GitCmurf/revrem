from __future__ import annotations

import json

import pytest

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


def test_stats_models_normalizes_malformed_duration_values(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"model_invocations": [
        {"phase": "review", "harness": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "high", "duration_seconds": "unknown", "outcome": "ok", "tokens": 42},
        {"phase": "review", "harness": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "high", "duration_seconds": 12.0, "outcome": "ok", "tokens": 42},
    ]}), encoding="utf-8")
    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"cwd": str(repo), "summary_path": str(summary)}) + "\n", encoding="utf-8")

    assert stats.main(["models", "--repo", str(repo), "--format", "json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["calls"] == 2
    assert row["duration_seconds"]["mean"] == 6.0


def test_stats_models_excludes_boolean_token_values(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"model_invocations": [
        {"phase": "review", "harness": "codex", "model": "gpt", "reasoning_effort": "high", "duration_seconds": 1, "outcome": "ok", "tokens": True},
    ]}), encoding="utf-8")
    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"cwd": str(repo), "summary_path": str(summary)}) + "\n", encoding="utf-8")

    assert stats.main(["models", "--repo", str(repo), "--format", "json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["token_coverage"] == "0/1"
    assert row["tokens"] is None


@pytest.mark.parametrize("summary_payload", [[], "not an object", 7, None])
def test_stats_models_skips_non_object_summary_payloads(
    tmp_path, monkeypatch, capsys, summary_payload
):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps(summary_payload), encoding="utf-8")
    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(
        json.dumps({"cwd": str(repo), "summary_path": str(summary)}) + "\n",
        encoding="utf-8",
    )

    assert stats.main(["models", "--repo", str(repo), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


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


def test_stats_models_filters_by_repo_before_limit(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    subdir = repo_root / "sub"
    subdir.mkdir()
    other_repo = tmp_path / "other_repo"
    other_repo.mkdir()
    (other_repo / ".git").mkdir()

    repo_summary = tmp_path / "repo_summary.json"
    repo_summary.write_text(
        json.dumps(
            {
                "model_invocations": [
                    {
                        "phase": "review",
                        "harness": "codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "high",
                        "duration_seconds": 12.0,
                        "outcome": "ok",
                        "tokens": 10,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    other_summary_1 = tmp_path / "other_summary_1.json"
    other_summary_1.write_text(json.dumps({"model_invocations": []}), encoding="utf-8")
    other_summary_2 = tmp_path / "other_summary_2.json"
    other_summary_2.write_text(json.dumps({"model_invocations": []}), encoding="utf-8")

    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(
        "\n".join(
            (
                json.dumps(
                    {"cwd": str(other_repo / "."), "summary_path": str(other_summary_2)}
                ),
                json.dumps(
                    {"cwd": str(other_repo / "."), "summary_path": str(other_summary_1)}
                ),
                json.dumps({"cwd": str(subdir), "summary_path": str(repo_summary)}),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        stats.main(["models", "--repo", str(subdir), "--limit", "1", "--format", "json"])
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["calls"] == 1
    assert rows[0]["model"] == "gpt-5.6-sol"


def test_stats_models_all_repos_resolves_relative_summary_path_against_record_cwd(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    summary_dir = repo / ".revrem" / "runs" / "run-1"
    summary_dir.mkdir(parents=True)
    summary = summary_dir / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "model_invocations": [
                    {
                        "phase": "review",
                        "harness": "codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "high",
                        "duration_seconds": 12.0,
                        "outcome": "ok",
                        "tokens": 42,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    history = home / "revrem" / "runs.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(
        json.dumps(
            {
                "cwd": str(repo),
                "summary_path": ".revrem/runs/run-1/summary.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "outside").mkdir()
    monkeypatch.chdir(tmp_path / "outside")

    assert stats.main(["models", "--all-repos", "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["calls"] == 1
    assert rows[0]["model"] == "gpt-5.6-sol"
