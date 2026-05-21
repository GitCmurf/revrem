"""A1 determinism seam: fake Clock + RunIdentity pin the machine contract.

Proves the Wave A1 injection works end-to-end: with a fake clock and identity,
the run's ``run_id``, ``started_at``, ``finished_at``, every ``events.jsonl``
timestamp, and the default artifact-dir suffix become deterministic. This is the
precondition the golden-master suite (A2) builds on.
"""

from __future__ import annotations

from support.fakes import FIXED_ISO, FIXED_RUN_ID, FakeClock, FakeRunIdentity

from code_review_loop import cli as MODULE
from code_review_loop import events


def _clear_review_runner(args, cwd, input_text=None, timeout_seconds=None):
    if args[1] == "review":
        return MODULE.CommandResult(
            list(args),
            0,
            stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
        )
    raise AssertionError(f"unexpected command: {args}")


def test_run_loop_timestamps_and_run_id_are_deterministic(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        final_review=False,
    )

    summary = MODULE.run_loop(
        config,
        _clear_review_runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
    )

    assert summary["run_id"] == FIXED_RUN_ID
    assert summary["started_at"] == FIXED_ISO
    assert summary["finished_at"] == FIXED_ISO

    records, _ = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    assert records, "expected at least one emitted event"
    assert {event.ts for event in records} == {FIXED_ISO}
    assert {event.run_id for event in records} == {FIXED_RUN_ID}


def test_default_artifact_dir_is_deterministic_under_fakes():
    path = MODULE.default_artifact_dir(clock=FakeClock(), identity=FakeRunIdentity())
    assert path.as_posix() == f".revrem/runs/20260102T030405Z-{FIXED_RUN_ID}"


def test_jsonl_sink_stamps_injected_clock(tmp_path):
    sink = events.JsonlSink(tmp_path, FIXED_RUN_ID, clock=FakeClock())
    event = sink.emit("phase_start", phase="review", iteration=1)
    sink.close()
    assert event.ts == FIXED_ISO
