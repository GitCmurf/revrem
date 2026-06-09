from unittest.mock import MagicMock

import pytest

import code_review_loop.run_guards as run_guards


def test_skips_if_not_commit_after_remediation():
    config = MagicMock()
    config.commit_after_remediation = False
    config.dry_run = False
    ctx = MagicMock()
    engine_state = MagicMock()
    run_guards.assert_worktree_stable_before_remediation(
        config, ctx, engine_state, expected_head=None
    )


def test_skips_if_not_inside_work_tree(monkeypatch):
    config = MagicMock()
    config.commit_after_remediation = True
    config.dry_run = False
    ctx = MagicMock()

    monkeypatch.setattr(run_guards, "lexical_git_repo_root", lambda c: None)

    engine_state = MagicMock()
    run_guards.assert_worktree_stable_before_remediation(
        config, ctx, engine_state, expected_head=None
    )

    ctx.runner.assert_not_called()


def test_raises_if_inside_work_tree_and_dirty(monkeypatch):
    config = MagicMock()
    config.commit_after_remediation = True
    config.dry_run = False
    ctx = MagicMock()

    engine_state = MagicMock()
    engine_state.acc.pending_check_failures = False
    engine_state.acc.commit_retry = False
    engine_state.acc.inner_check_retry_count = 0

    monkeypatch.setattr(run_guards, "lexical_git_repo_root", lambda c: "/mock/repo")
    monkeypatch.setattr(run_guards, "current_head", lambda c, cx: "mock-head")
    monkeypatch.setattr(
        run_guards,
        "current_non_artifact_status_lines",
        lambda c, cx: [" M dirty.py"],
    )

    with pytest.raises(RuntimeError, match="worktree changed during run before remediation"):
        run_guards.assert_worktree_stable_before_remediation(
            config, ctx, engine_state, expected_head="mock-head"
        )


def test_does_not_raise_if_inside_work_tree_and_clean(monkeypatch):
    config = MagicMock()
    config.commit_after_remediation = True
    config.dry_run = False
    ctx = MagicMock()

    engine_state = MagicMock()
    engine_state.acc.pending_check_failures = False
    engine_state.acc.commit_retry = False
    engine_state.acc.inner_check_retry_count = 0

    monkeypatch.setattr(run_guards, "lexical_git_repo_root", lambda c: "/mock/repo")
    monkeypatch.setattr(run_guards, "current_head", lambda c, cx: "mock-head")
    monkeypatch.setattr(run_guards, "current_non_artifact_status_lines", lambda c, cx: [])

    run_guards.assert_worktree_stable_before_remediation(
        config, ctx, engine_state, expected_head="mock-head"
    )
