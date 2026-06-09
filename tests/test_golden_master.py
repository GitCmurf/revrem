"""Golden-master suite — machine-contract change detector (REVREM-TASK-003 A2/C3).

A2a vertical slice: one end-to-end path (loop, review-clear) proving the whole
machinery — fakes -> deterministic run -> normalizer -> committed snapshot ->
fail-on-diff. A2b adds the remaining loop terminations (findings-exhausted,
budget-ceiling, cancel) on top of these helpers; per-subcommand snapshots are
deferred to A2c.

Snapshots cover the machine contract only (summary JSON, events.jsonl); human
presentation is out of scope (C3).
"""

from __future__ import annotations

import pytest
from support.fakes import FIXED_RUN_ID, FakeClock, FakeRunIdentity, FakeRunner
from support.normalize import CWD_PLACEHOLDER, DURATION_PLACEHOLDER, normalize
from support.snapshot import assert_snapshot

import tests.support.application_runner as runner_mod
from code_review_loop import budgets, events
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import RunLoopFailed

CLEAR_REVIEW_STDOUT = '{"findings": [], "overall_correctness": "patch is correct"}\n'
FINDINGS_REVIEW_STDOUT = "REVIEW_STATUS: findings\n"


def _loop_config(tmp_path, **overrides):
    base = {
        "base": "main",
        "max_iterations": 1,
        "codex_bin": "codex",
        "cwd": tmp_path,
        "artifact_dir": tmp_path / "artifacts",
        "progress": False,
        "final_review": False,
    }
    base.update(overrides)
    return LoopConfig(**base)


def _drive_loop(config, runner, tmp_path):
    """Run the loop and return (summary, event_dicts) for any termination.

    Paths that fail (budget, cancel) raise ``RunLoopFailed`` carrying the
    summary; both the returned and the raised summary are part of the machine
    contract, so normalize either. Callers must assert the expected termination
    shape (e.g. ``stopped_reason``) before snapshotting, since this helper hides
    the return-vs-raise distinction.
    """
    try:
        summary = runner_mod.run_loop(
            config, runner, clock=FakeClock(), identity=FakeRunIdentity()
        ).to_dict()
    except RunLoopFailed as exc:
        summary = exc.summary
    records, _ = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    return summary, [event.to_dict() for event in records]


def _run_clear_path(tmp_path):
    runner = FakeRunner({"review": CommandResult([], 0, stdout=CLEAR_REVIEW_STDOUT)})
    return _drive_loop(_loop_config(tmp_path), runner, tmp_path)


def test_loop_clear_path_summary_matches_golden(tmp_path):
    summary, _ = _run_clear_path(tmp_path)
    assert_snapshot("loop_clear_summary", normalize(summary, run_dir=tmp_path))


def test_loop_clear_path_events_match_golden(tmp_path):
    _, event_dicts = _run_clear_path(tmp_path)
    assert_snapshot("loop_clear_events", normalize(event_dicts, run_dir=tmp_path))


# --- A2b: findings remain, iterations exhausted (no triage, no final review) ---


def _run_findings_path(tmp_path):
    runner = FakeRunner(
        {
            "review": CommandResult([], 0, stdout=FINDINGS_REVIEW_STDOUT),
            "exec": CommandResult([], 0, stdout="remediated\n"),
        }
    )
    return _drive_loop(_loop_config(tmp_path), runner, tmp_path)


def test_loop_findings_path_summary_matches_golden(tmp_path):
    summary, _ = _run_findings_path(tmp_path)
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert_snapshot("loop_findings_summary", normalize(summary, run_dir=tmp_path))


def test_loop_findings_path_events_match_golden(tmp_path):
    _, event_dicts = _run_findings_path(tmp_path)
    assert_snapshot("loop_findings_events", normalize(event_dicts, run_dir=tmp_path))


# --- A2b: token budget ceiling hit during review ---


def _run_budget_path(tmp_path):
    runner = FakeRunner({"review": CommandResult([], 0, stdout=FINDINGS_REVIEW_STDOUT, tokens=100)})
    config = _loop_config(tmp_path, budget_config=budgets.BudgetConfig(max_tokens=10))
    return _drive_loop(config, runner, tmp_path)


def test_loop_budget_path_summary_matches_golden(tmp_path):
    summary, _ = _run_budget_path(tmp_path)
    assert summary["stopped_reason"] == "budget_ceiling_hit"
    assert_snapshot("loop_budget_summary", normalize(summary, run_dir=tmp_path))


def test_loop_budget_path_events_match_golden(tmp_path):
    _, event_dicts = _run_budget_path(tmp_path)
    assert_snapshot("loop_budget_events", normalize(event_dicts, run_dir=tmp_path))


# --- A2b: operator cancellation (KeyboardInterrupt during review) ---


def _run_cancel_path(tmp_path):
    runner = FakeRunner({"review": KeyboardInterrupt("operator interrupt")})
    return _drive_loop(_loop_config(tmp_path), runner, tmp_path)


def test_loop_cancel_path_summary_matches_golden(tmp_path):
    summary, _ = _run_cancel_path(tmp_path)
    assert summary["stopped_reason"] == "cancelled"
    assert_snapshot("loop_cancel_summary", normalize(summary, run_dir=tmp_path))


def test_loop_cancel_path_events_match_golden(tmp_path):
    _, event_dicts = _run_cancel_path(tmp_path)
    assert_snapshot("loop_cancel_events", normalize(event_dicts, run_dir=tmp_path))


# --- normalizer unit tests (pure; no loop run needed) ---


def test_normalizer_replaces_run_dir_and_durations():
    raw = {
        "artifact_dir": "/tmp/xyz/artifacts",
        "budgets": {"wall_elapsed_seconds": 0.2231, "max_tokens": None},
        "paths": ["/tmp/xyz/a.txt", "/elsewhere/b.txt"],
        "run_id": FIXED_RUN_ID,
    }
    out = normalize(raw, run_dir="/tmp/xyz")
    assert out["artifact_dir"] == f"{CWD_PLACEHOLDER}/artifacts"
    assert out["budgets"]["wall_elapsed_seconds"] == DURATION_PLACEHOLDER
    assert out["paths"] == [f"{CWD_PLACEHOLDER}/a.txt", "/elsewhere/b.txt"]
    assert out["run_id"] == FIXED_RUN_ID  # untouched


def test_normalizer_leaves_boolean_durations_alone():
    # a bool must not be mistaken for a numeric duration
    out = normalize({"wall_elapsed_seconds": False}, run_dir="/tmp/xyz")
    assert out["wall_elapsed_seconds"] is False


# --- the change-detector actually detects (negative test) ---


def test_assert_snapshot_raises_on_mismatch(tmp_path, monkeypatch):
    import support.snapshot as snap

    monkeypatch.setattr(snap, "SNAPSHOT_DIR", tmp_path)
    snap.assert_snapshot("demo", {"a": 1}, update=True)  # establish baseline
    snap.assert_snapshot("demo", {"a": 1})  # equal -> passes
    with pytest.raises(AssertionError, match="snapshot 'demo' changed"):
        snap.assert_snapshot("demo", {"a": 2})  # changed -> fails
