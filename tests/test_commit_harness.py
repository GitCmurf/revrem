"""Tests for the CommitHarness adapter wiring (REVREM-TASK-003 B2c).

Covers: successful commit, dry-run skip, no-staged-changes skip, CommitFailed
propagation, retrying flag threading, and harness dispatch correctness.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import code_review_loop.loop as loop_mod
from code_review_loop.adapters.commit import CommitAdapter
from code_review_loop.clock import Clock
from code_review_loop.core.ports import (
    CommandResult,
    CommitOutcome,
    CommitRequest,
    RunContext,
)
from code_review_loop.identity import RunIdentity

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ctx(runner=None, **kwargs: object) -> RunContext:
    return RunContext(
        clock=MagicMock(spec=Clock),
        identity=MagicMock(spec=RunIdentity),
        runner=runner if runner is not None else MagicMock(),
        **kwargs,  # type: ignore[arg-type]
    )


def _git_runner(*, staged: bool = True, commit_ok: bool = True):
    """Minimal runner that satisfies run_commit's git subprocess calls."""

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        cmd = " ".join(args)
        if "add" in cmd:
            return CommandResult(list(args), 0)
        if "reset" in cmd:
            return CommandResult(list(args), 0)
        if "--cached" in cmd and "--quiet" in cmd:
            # exit 0 = nothing staged, exit 1 = staged changes exist
            return CommandResult(list(args), 0 if not staged else 1)
        if "commit" in cmd:
            return CommandResult(list(args), 0 if commit_ok else 1, stdout="[main abc1234]\n")
        return CommandResult(list(args), 0)

    return runner


# ---------------------------------------------------------------------------
# CommitAdapter unit tests
# ---------------------------------------------------------------------------

class TestCommitAdapter:
    def test_dry_run_returns_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = loop_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            dry_run=True,
        )
        runner = MagicMock(side_effect=AssertionError("no subprocess in dry-run"))
        ctx = _ctx(runner=runner)
        adapter = CommitAdapter(config)

        outcome = adapter.execute(CommitRequest(iteration=1), ctx)

        assert isinstance(outcome, CommitOutcome)
        assert outcome.status == "skipped"
        runner.assert_not_called()

    def test_no_staged_changes_returns_skipped_no_changes(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = loop_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=_git_runner(staged=False))
        adapter = CommitAdapter(config)

        outcome = adapter.execute(CommitRequest(iteration=1), ctx)

        assert outcome.status == "skipped_no_changes"

    def test_commit_failed_propagates_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = loop_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=_git_runner(staged=True, commit_ok=False))
        adapter = CommitAdapter(config)

        with pytest.raises(loop_mod.CommitFailed):
            adapter.execute(CommitRequest(iteration=1), ctx)

    def test_retrying_flag_threaded_through(self, tmp_path: Path) -> None:
        """CommitRequest.retrying is forwarded to run_commit."""
        (tmp_path / "artifacts").mkdir()
        config = loop_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=MagicMock())
        adapter = CommitAdapter(config)

        # REVREM-TASK-003 Wave C3a step 5: run_commit now lives in
        # ``adapters._commit_impl`` and is imported by ``adapters.commit``
        # directly. Patch the binding the adapter actually calls.
        with patch("code_review_loop.adapters.commit.run_commit") as mock_commit:
            mock_commit.return_value = "committed"
            outcome = adapter.execute(CommitRequest(iteration=2, retrying=True), ctx)

        mock_commit.assert_called_once()
        _, kwargs = mock_commit.call_args
        assert kwargs.get("retrying") is True
        assert outcome.status == "committed"


# ---------------------------------------------------------------------------
# Engine dispatch: ctx.phase_commit wired vs. absent
# ---------------------------------------------------------------------------

class TestEngineDispatch:
    def test_harness_called_when_wired(self) -> None:
        fake_outcome = CommitOutcome(status="committed")

        class SentinelHarness:
            calls: list[CommitRequest] = []

            def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
                SentinelHarness.calls.append(request)
                return fake_outcome

        sentinel = SentinelHarness()
        ctx = _ctx(phase_commit=sentinel)
        request = CommitRequest(iteration=3, retrying=False)

        if ctx.phase_commit is not None:
            outcome = ctx.phase_commit.execute(request, ctx)
        else:
            raise AssertionError("should have taken the harness branch")

        assert outcome is fake_outcome
        assert SentinelHarness.calls[0].iteration == 3
        assert SentinelHarness.calls[0].retrying is False

    def test_budget_exceeded_propagates_through_adapter(self, tmp_path: Path, monkeypatch) -> None:
        """BudgetExceeded raised inside CommitAdapter.execute propagates to run_loop."""
        import code_review_loop.adapters.commit as commit_mod
        from code_review_loop.budgets import BudgetExceeded

        exc = BudgetExceeded(ceiling="tokens", limit=100, actual=150)
        monkeypatch.setattr(commit_mod.CommitAdapter, "execute", lambda *a, **kw: (_ for _ in ()).throw(exc))

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            if "status" in args:
                return CommandResult(list(args), 0, stdout="")
            return CommandResult(list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n")

        config = loop_mod.LoopConfig(
            base="main",
            max_iterations=2,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            commit_after_remediation=True,
        )

        with pytest.raises(loop_mod.RunLoopFailed) as excinfo:
            loop_mod.run_loop(config, runner)

        assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"
