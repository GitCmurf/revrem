from __future__ import annotations

from code_review_loop import cli, events


def test_replay_renders_events_without_runner_or_harness(tmp_path, capsys):
    sink = events.JsonlSink(tmp_path, "run-1")
    sink.emit("phase_start", phase="review", iteration=1, payload={"message": "start"})
    sink.emit("phase_result", phase="review", iteration=1, payload={"status": "clear"})
    sink.close()

    code = cli.main(["replay", str(tmp_path)])

    assert code == 0
    assert capsys.readouterr().out == (
        "0001|review|1|phase_start: start\n"
        "0002|review|1|phase_result: clear\n"
    )


def test_replay_returns_nonzero_for_truncated_events(tmp_path, capsys):
    (tmp_path / "events.jsonl").write_text(
        '{"schema_version":"1.0","run_id":"run-1","seq":1,"ts":"2026-05-12T00:00:00Z","kind":"summary","phase":null,"iteration":null,"payload":{"status":"clear"}}\n'
        '{"schema_version":',
        encoding="utf-8",
    )

    code = cli.main(["replay", str(tmp_path)])

    assert code == 1
    assert "truncated_events_jsonl" in capsys.readouterr().out
