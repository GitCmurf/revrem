"""Unit tests for the RunState aggregate (REVREM-TASK-003 A3).

A3 is a *shadow* wave: RunState wraps the live in-loop summary dict and the
iterations list (the same objects the loop reads), exposing the scalar terminal
writes as transition methods. The byte-for-byte equivalence gate for the loop
itself is the A2 golden masters staying identical; these tests pin RunState's
own contract in isolation.
"""

from __future__ import annotations

from code_review_loop.core.state import RunState

INITIAL_KEYS = {
    "base",
    "git_state",
    "resume_config",
    "run_id",
    "started_at",
    "profile",
    "max_iterations",
    "artifact_dir",
    "iterations",
    "commit_on_hook_failure",
    "commit_no_verify",
    "budgets",
    "final_status",
    "initial_review_file",
    "pending_check_failures",
    "stopped_reason",
}


def _make(**overrides):
    base = {
        "base": "main",
        "git_state": {"available": False},
        "resume_config": {"base": "main"},
        "run_id": "run-1",
        "started_at": "2026-01-02T03:04:05Z",
        "profile": None,
        "max_iterations": 3,
        "artifact_dir": "/tmp/artifacts",
        "commit_on_hook_failure": "remediate",
        "budgets": {"max_tokens": None},
        "initial_review_file": None,
    }
    base.update(overrides)
    return RunState.create(**base)


def test_create_produces_the_initial_summary_shape():
    state = _make()
    summary = state.to_dict()
    assert set(summary) == INITIAL_KEYS
    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] is None
    assert summary["pending_check_failures"] is False


def test_commit_no_verify_is_derived_from_hook_policy():
    assert _make(commit_on_hook_failure="no-verify").to_dict()["commit_no_verify"] is True
    assert _make(commit_on_hook_failure="remediate").to_dict()["commit_no_verify"] is False


def test_to_dict_returns_the_live_dict_not_a_copy():
    state = _make()
    assert state.to_dict() is state.to_dict()


def test_iterations_is_the_same_list_object_as_in_the_summary():
    state = _make()
    assert state.iterations is state.to_dict()["iterations"]
    state.iterations.append({"iteration": 1})
    assert state.to_dict()["iterations"] == [{"iteration": 1}]


def test_scalar_transitions_mutate_the_live_dict():
    state = _make()
    state.set_final_status("clear")
    state.set_stopped_reason("review_clear")
    state.set_error("boom")
    state.set_latest_review_excerpt("excerpt")
    state.set_suppressed_findings_count(2)
    state.set_pending_check_failures(True)
    state.set_staged_changes_left(True)
    summary = state.to_dict()
    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "review_clear"
    assert summary["error"] == "boom"
    assert summary["latest_review_excerpt"] == "excerpt"
    assert summary["suppressed_findings_count"] == 2
    assert summary["pending_check_failures"] is True
    assert summary["staged_changes_left"] is True
