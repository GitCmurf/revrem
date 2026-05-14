from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from code_review_loop import events
from code_review_loop._compat_jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def test_in_memory_sink_assigns_gap_free_sequence():
    sink = events.InMemorySink("run-1")

    first = sink.emit("phase_start", phase="review", iteration=1, payload={"command": "codex"})
    second = sink.emit("phase_result", phase="review", iteration=1, payload={"status": "findings"})

    assert first.seq == 1
    assert second.seq == 2
    assert [event.kind for event in sink.events] == ["phase_start", "phase_result"]


def test_renderer_sink_dispatches_events_to_callback():
    rendered: list[events.Event] = []
    sink = events.RendererSink("run-1", rendered.append)

    emitted = sink.emit("phase_start", phase="review", iteration=1, payload={"command": "codex review"})
    sink.emit("phase_result", phase="review", iteration=1, payload={"status": "clear"})
    sink.close()

    assert emitted.seq == 1
    assert [event.kind for event in rendered] == ["phase_start", "phase_result"]
    assert [event.seq for event in rendered] == [1, 2]


def test_renderer_sink_does_not_block_on_slow_consumer():
    def slow_renderer(_event: events.Event) -> None:
        time.sleep(0.2)

    sink = events.RendererSink("run-1", slow_renderer, max_queue=1, close_timeout_seconds=0.01)

    started = time.monotonic()
    for _ in range(25):
        sink.emit("phase_output", phase="review", iteration=1, payload={"message": "chunk"})
    elapsed = time.monotonic() - started
    sink.close()

    assert elapsed < 0.5
    assert sink.dropped_events > 0


def test_renderer_sink_counts_renderer_errors_without_failing_producer():
    def broken_renderer(_event: events.Event) -> None:
        raise RuntimeError("renderer failed")

    sink = events.RendererSink("run-1", broken_renderer)

    event = sink.emit("warning", phase="review", payload={"message": "still recorded"})
    sink.close()

    assert event.kind == "warning"
    assert sink.render_errors == 1


def test_jsonl_sink_writes_schema_valid_events(tmp_path):
    sink = events.JsonlSink(tmp_path, "run-1")
    sink.emit("phase_start", phase="review", iteration=1, payload={"command": "codex review"})
    sink.emit("phase_result", phase="review", iteration=1, payload={"status": "clear"})
    sink.close()
    schema = json.loads((ROOT / "docs/52-api/schemas/events-v1.schema.json").read_text(encoding="utf-8"))

    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    for line in lines:
        validate(json.loads(line), schema)


def test_jsonl_sink_truncates_existing_file_for_new_run(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(
            events.make_event(
                run_id="old-run",
                seq=1,
                kind="summary",
                payload={"status": "done"},
            ).to_dict()
        )
        + "\n",
        encoding="utf-8",
    )

    sink = events.JsonlSink(tmp_path, "run-1")
    sink.emit("phase_start", phase="review", iteration=1, payload={"command": "codex review"})
    sink.close()

    records, truncated = events.read_events(path)

    assert truncated is False
    assert len(records) == 1
    assert records[0].run_id == "run-1"
    assert records[0].seq == 1


def test_jsonl_sink_rejects_symlinked_event_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "events.jsonl").symlink_to(outside / "events.jsonl")

    with pytest.raises(events.artifacts.ArtifactPathError, match="symlink"):
        events.JsonlSink(run_dir, "run-1")


def test_read_events_tolerates_truncated_tail(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(
            events.make_event(
                run_id="run-1",
                seq=1,
                kind="phase_start",
                phase="review",
                iteration=1,
                payload={},
            ).to_dict()
        )
        + "\n"
        + '{"schema_version": "1.0", "run_id": ',
        encoding="utf-8",
    )

    records, truncated = events.read_events(path)

    assert truncated is True
    assert [event.kind for event in records] == ["phase_start", "failure"]
    assert records[-1].payload["reason"] == "truncated_events_jsonl"


def test_read_events_rejects_sequence_gap(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(events.make_event(run_id="run-1", seq=2, kind="summary").to_dict()) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="event seq gap"):
        events.read_events(path)


def test_compact_renderer_is_deterministic():
    rendered = events.render_compact(
        [
            events.make_event(
                run_id="run-1",
                seq=1,
                kind="phase_start",
                phase="review",
                iteration=1,
                payload={"message": "start"},
                ts="2026-05-12T00:00:00Z",
            ),
            events.make_event(
                run_id="run-1",
                seq=2,
                kind="phase_result",
                phase="review",
                iteration=1,
                payload={"status": "clear"},
                ts="2026-05-12T00:00:01Z",
            ),
        ]
    )

    assert rendered == "0001|review|1|phase_start: start\n0002|review|1|phase_result: clear\n"
