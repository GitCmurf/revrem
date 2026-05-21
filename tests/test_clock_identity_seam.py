"""A1 determinism seam: fake Clock + RunIdentity pin the machine contract.

Proves the Wave A1 injection works end-to-end: with a fake clock and identity,
the run's ``run_id``, ``started_at``, ``finished_at``, every ``events.jsonl``
timestamp, and the default artifact-dir suffix become deterministic. This is the
precondition the golden-master suite (A2) builds on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from code_review_loop import cli as MODULE
from code_review_loop import events

FIXED_MOMENT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FIXED_ISO = "2026-01-02T03:04:05Z"
FIXED_RUN_ID = "deadbeefcafe0000deadbeefcafe0000"


class FakeClock:
    def __init__(self, moment: datetime = FIXED_MOMENT, monotonic: float = 1000.0):
        self._moment = moment
        self._monotonic = monotonic

    def now(self) -> datetime:
        return self._moment

    def monotonic(self) -> float:
        return self._monotonic


class FakeRunIdentity:
    def __init__(self, value: str = FIXED_RUN_ID):
        self._value = value

    def new_run_id(self) -> str:
        return self._value


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
