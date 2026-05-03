from __future__ import annotations

import json

from code_review_loop import run_history


def test_append_and_read_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    summary = {
        "run_id": "run-1",
        "started_at": "2026-05-02T10:00:00Z",
        "base": "main",
        "profile": "final-pr",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "max_iterations": 2,
        "pending_check_failures": False,
        "artifact_dir": "tmp/code-review-loop/run-1",
        "iterations": [{"iteration": 1, "review_status": "clear"}],
        "artifact_paths": {
            "summary": "tmp/code-review-loop/run-1/summary.json",
            "reviews": ["tmp/code-review-loop/run-1/review-1.txt"],
        },
    }

    path = run_history.append_history(summary, cwd=tmp_path)
    records = run_history.read_history(path)

    assert path == tmp_path / "home" / ".local" / "share" / "revrem" / "runs.jsonl"
    assert len(records) == 1
    assert records[0]["schema_version"] == "1.0"
    assert records[0]["run_id"] == "run-1"
    assert records[0]["profile"] == "final-pr"
    assert records[0]["iteration_count"] == 1
    assert records[0]["summary_path"] == "tmp/code-review-loop/run-1/summary.json"
    assert records[0]["artifact_paths"]["summary"] == "tmp/code-review-loop/run-1/summary.json"
    assert records[0]["artifact_paths"]["reviews"] == ["tmp/code-review-loop/run-1/review-1.txt"]


def test_history_uses_xdg_data_home_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert run_history.default_history_path() == tmp_path / "xdg" / "revrem" / "runs.jsonl"


def test_read_history_returns_newest_first_and_applies_limit(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"run_id": "old"}),
                "{not valid json",
                json.dumps({"run_id": "new"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert [record["run_id"] for record in run_history.read_history(path)] == ["new", "old"]
    assert [record["run_id"] for record in run_history.read_history(path, limit=1)] == ["new"]


def test_read_history_skips_malformed_lines(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"run_id": "old"}),
                "{\"run_id\":",
                json.dumps({"run_id": "new"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert [record["run_id"] for record in run_history.read_history(path)] == ["new", "old"]
