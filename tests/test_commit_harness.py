"""Tests for the CommitHarness adapter wiring (REVREM-TASK-003 B2c).

Covers: successful commit, dry-run skip, no-staged-changes skip, CommitFailed
propagation, retrying flag threading, and harness dispatch correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from support.phase_harnesses import phase_harness_kwargs

import tests.support.application_runner as runner_mod
from code_review_loop.adapters.commit import (
    COMMIT_MESSAGE_SIDE_EFFECT_WARNING,
    CommitAdapter,
    _commit_message_worktree_status,
    _handle_commit_message_side_effects,
)
from code_review_loop.adapters.phase_support import CommitFailed
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import (
    CommandResult,
    CommitOutcome,
    CommitRequest,
    RunContext,
)
from code_review_loop.identity import RunIdentity
from code_review_loop.runtime import RunLoopFailed

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ctx(runner=None, **kwargs: object) -> RunContext:
    return RunContext(
        clock=MagicMock(spec=Clock),
        identity=MagicMock(spec=RunIdentity),
        runner=runner if runner is not None else MagicMock(),
        **phase_harness_kwargs(**kwargs),  # type: ignore[arg-type]
    )


def _git_runner(*, staged: bool = True, commit_ok: bool = True, repo_root: Path | None = None):
    """Minimal runner that satisfies run_commit's git subprocess calls."""

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        cmd = " ".join(args)
        if args[:4] == ["git", "-C", str(cwd), "rev-parse"] and args[4:] == ["--show-toplevel"]:
            if repo_root is None:
                return CommandResult(list(args), 1, stderr="fatal: not a git repository\n")
            return CommandResult(list(args), 0, stdout=f"{repo_root}\n")
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
        config = LoopConfig(
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
        (tmp_path / ".git").mkdir()
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=_git_runner(staged=False, repo_root=tmp_path))
        adapter = CommitAdapter(config)

        outcome = adapter.execute(CommitRequest(iteration=1), ctx)

        assert outcome.status == "skipped_no_changes"

    def test_no_staged_changes_without_repo_root_returns_skipped_no_changes(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=_git_runner(staged=False, repo_root=None))
        adapter = CommitAdapter(config)

        outcome = adapter.execute(CommitRequest(iteration=1), ctx)

        assert outcome.status == "skipped_no_changes"

    def test_commit_failed_propagates_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=_git_runner(staged=True, commit_ok=False, repo_root=tmp_path))
        adapter = CommitAdapter(config)

        with pytest.raises(CommitFailed):
            adapter.execute(CommitRequest(iteration=1), ctx)

    def test_retrying_flag_threaded_through(self, tmp_path: Path) -> None:
        """CommitRequest.retrying is forwarded to run_commit."""
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=MagicMock())
        adapter = CommitAdapter(config)

        # REVREM-TASK-003 Wave C3a step 5: run_commit now lives in
        # ``adapters.commit`` and is imported by ``adapters.commit``
        # directly. Patch the binding the adapter actually calls.
        with patch("code_review_loop.adapters.commit.run_commit") as mock_commit:
            mock_commit.return_value = "committed"
            outcome = adapter.execute(CommitRequest(iteration=2, retrying=True), ctx)

        mock_commit.assert_called_once()
        _, kwargs = mock_commit.call_args
        assert kwargs.get("retrying") is True
        assert outcome.status == "committed"

    def test_adopts_clean_commit_message_self_commit(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        artifact_dir = repo / "artifacts"
        artifact_dir.mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=repo,
            artifact_dir=artifact_dir,
            commit_message_model="test-model",
        )
        head = {"value": "before"}
        cached_raw = {"value": ":100644 100644 old new M\tfile.py\n"}
        commit_commands: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            argv = list(args)
            if argv[:4] == ["git", "-C", str(repo), "rev-parse"]:
                return CommandResult(argv, 0, stdout=f"{repo}\n")
            if argv == ["git", "add", "-A"]:
                return CommandResult(argv, 0)
            if argv[:4] == ["git", "-C", str(repo), "reset"]:
                return CommandResult(argv, 0)
            if argv == ["git", "diff", "--cached", "--quiet"]:
                return CommandResult(argv, 0 if not cached_raw["value"] else 1)
            if argv == ["git", "diff", "--cached", "--stat"]:
                return CommandResult(argv, 0, stdout=" file.py | 1 +\n")
            if argv == ["git", "diff", "--cached", "--name-only"]:
                return CommandResult(argv, 0, stdout="file.py\n")
            if argv == ["git", "rev-parse", "HEAD"]:
                return CommandResult(argv, 0, stdout=f"{head['value']}\n")
            if argv == ["git", "diff", "--cached", "--raw"]:
                return CommandResult(argv, 0, stdout=cached_raw["value"])
            if argv == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
                return CommandResult(argv, 0, stdout="")
            if argv[:2] == ["git", "commit"]:
                commit_commands.append(argv)
                return CommandResult(argv, 1, stderr="should not be called\n")
            head["value"] = "after"
            cached_raw["value"] = ""
            return CommandResult(argv, 0, stdout="fix(core): self committed (RevRem)\n")

        ctx = _ctx(runner=runner)
        adapter = CommitAdapter(config)

        outcome = adapter.execute(CommitRequest(iteration=7), ctx)

        assert outcome.status == "committed"
        assert commit_commands == []
        side_effects = json.loads(
            (artifact_dir / "commit-7-message-side-effects.json").read_text(encoding="utf-8")
        )
        assert side_effects["kind"] == "self_commit_adopted"
        assert side_effects["severity"] == "warning"
        assert side_effects["head_before"] == "before"
        assert side_effects["head_after"] == "after"
        assert side_effects["warning"] == COMMIT_MESSAGE_SIDE_EFFECT_WARNING
        assert COMMIT_MESSAGE_SIDE_EFFECT_WARNING in (artifact_dir / "commit-7.txt").read_text(
            encoding="utf-8"
        )

    def test_rejects_commit_message_staged_diff_mutation_without_head_change(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        artifact_dir = repo / "artifacts"
        artifact_dir.mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=repo,
            artifact_dir=artifact_dir,
            commit_message_model="test-model",
        )
        cached_raw = {"value": ":100644 100644 old new M\tfile.py\n"}

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            argv = list(args)
            if argv[:4] == ["git", "-C", str(repo), "rev-parse"]:
                return CommandResult(argv, 0, stdout=f"{repo}\n")
            if argv == ["git", "add", "-A"]:
                return CommandResult(argv, 0)
            if argv[:4] == ["git", "-C", str(repo), "reset"]:
                return CommandResult(argv, 0)
            if argv == ["git", "diff", "--cached", "--quiet"]:
                return CommandResult(argv, 0 if not cached_raw["value"] else 1)
            if argv == ["git", "diff", "--cached", "--stat"]:
                return CommandResult(argv, 0, stdout=" file.py | 1 +\n")
            if argv == ["git", "diff", "--cached", "--name-only"]:
                return CommandResult(argv, 0, stdout="file.py\n")
            if argv == ["git", "rev-parse", "HEAD"]:
                return CommandResult(argv, 0, stdout="same-head\n")
            if argv == ["git", "diff", "--cached", "--raw"]:
                return CommandResult(argv, 0, stdout=cached_raw["value"])
            if argv == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
                return CommandResult(argv, 0, stdout="")
            cached_raw["value"] = ""
            return CommandResult(argv, 0, stdout="fix(core): invalid mutation (RevRem)\n")

        ctx = _ctx(runner=runner)
        adapter = CommitAdapter(config)

        with pytest.raises(RuntimeError, match="mutated repository HEAD or staged changes"):
            adapter.execute(CommitRequest(iteration=8), ctx)

        side_effects = json.loads(
            (artifact_dir / "commit-8-message-side-effects.json").read_text(encoding="utf-8")
        )
        assert side_effects["kind"] == "unsafe_repo_mutation"
        assert side_effects["severity"] == "error"
        assert side_effects["cached_diff_changed"] is True


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

        outcome = ctx.phase_commit.execute(request, ctx)

        assert outcome is fake_outcome
        assert SentinelHarness.calls[0].iteration == 3
        assert SentinelHarness.calls[0].retrying is False

    def test_budget_exceeded_propagates_through_adapter(self, tmp_path: Path, monkeypatch) -> None:
        """BudgetExceeded raised inside CommitAdapter.execute propagates to run_loop."""
        import code_review_loop.adapters.commit as commit_mod
        from code_review_loop.budgets import BudgetExceeded

        exc = BudgetExceeded(ceiling="tokens", limit=100, actual=150)
        monkeypatch.setattr(
            commit_mod.CommitAdapter, "execute", lambda *a, **kw: (_ for _ in ()).throw(exc)
        )

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            if "status" in args:
                return CommandResult(list(args), 0, stdout="")
            return CommandResult(
                list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
            )

        config = LoopConfig(
            base="main",
            max_iterations=2,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            commit_after_remediation=True,
        )

        with pytest.raises(RunLoopFailed) as excinfo:
            runner_mod.run_loop(config, runner)

        assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"


# ---------------------------------------------------------------------------
# Commit-message side-effect cleanup path resolution
# ---------------------------------------------------------------------------


class TestCommitMessageSideEffects:
    """``_handle_commit_message_side_effects`` must resolve ``??`` paths from
    the lexical git repository root so root-level helper files created by the
    commit-message model are removed (and reported as cleaned) rather than
    being classified as missing/unsafe worktree paths when RevRem is launched
    from a subdirectory.
    """

    def test_removes_root_level_helper_file_when_launched_from_subdirectory(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        subdir = repo / "packages" / "app"
        subdir.mkdir(parents=True)
        (repo / ".git").mkdir()
        artifact_dir = subdir / "artifacts"
        artifact_dir.mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=subdir,
            artifact_dir=artifact_dir,
        )

        helper_path = repo / "commit-subject.txt"
        helper_path.write_text("fix(review): cleanup from subdir (RevRem)\n", encoding="utf-8")

        status_outputs = iter(["", "?? commit-subject.txt\x00"])

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            if args[:5] == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
                return CommandResult(list(args), 0, stdout=next(status_outputs))
            return CommandResult(list(args), 0)

        before_status = _commit_message_worktree_status(config, runner)
        assert before_status == set()
        outcome, removed = _handle_commit_message_side_effects(
            config,
            runner,
            4,
            before_status=before_status,
            timeout_seconds=None,
        )

        assert outcome == "fallback"
        assert removed == ["commit-subject.txt"]
        assert not helper_path.exists()
        side_effects = json.loads(
            (artifact_dir / "commit-4-message-side-effects.json").read_text(encoding="utf-8")
        )
        assert side_effects["created_paths_removed"] == ["commit-subject.txt"]
        assert side_effects["unsafe_status_lines"] == []

    def test_does_not_target_subdirectory_path_for_root_level_helper(self, tmp_path: Path) -> None:
        """When RevRem is launched from a subdirectory and the commit-message
        model writes a root-level helper file, the cleanup must remove the
        root-level file and leave a same-named file under the launch
        directory untouched.
        """
        repo = tmp_path / "repo"
        subdir = repo / "packages" / "app"
        subdir.mkdir(parents=True)
        (repo / ".git").mkdir()
        artifact_dir = subdir / "artifacts"
        artifact_dir.mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=subdir,
            artifact_dir=artifact_dir,
        )

        helper_path = repo / "commit-subject.txt"
        helper_path.write_text("fix(review): cleanup from subdir (RevRem)\n", encoding="utf-8")
        decoy = subdir / "commit-subject.txt"
        decoy.write_text("decoy under subdir should be preserved\n", encoding="utf-8")

        status_outputs = iter(["", "?? commit-subject.txt\x00"])

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            if args[:5] == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
                return CommandResult(list(args), 0, stdout=next(status_outputs))
            return CommandResult(list(args), 0)

        before_status = _commit_message_worktree_status(config, runner)
        outcome, removed = _handle_commit_message_side_effects(
            config,
            runner,
            5,
            before_status=before_status,
            timeout_seconds=None,
        )

        assert outcome == "fallback"
        assert removed == ["commit-subject.txt"]
        assert not helper_path.exists()
        assert decoy.exists(), "decoy file under launch directory must be preserved"
        side_effects = json.loads(
            (artifact_dir / "commit-5-message-side-effects.json").read_text(encoding="utf-8")
        )
        assert side_effects["created_paths_removed"] == ["commit-subject.txt"]
        assert side_effects["unsafe_status_lines"] == []

    def test_rejects_path_escaping_repo_root(self, tmp_path: Path) -> None:
        """Status paths that escape the repository root must still be
        classified as unsafe; the repo-root fix must not weaken the
        containment check.
        """
        repo = tmp_path / "repo"
        subdir = repo / "packages" / "app"
        subdir.mkdir(parents=True)
        (repo / ".git").mkdir()
        artifact_dir = subdir / "artifacts"
        artifact_dir.mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=subdir,
            artifact_dir=artifact_dir,
        )

        status_outputs = iter(["", "?? ../escape.txt\x00"])

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            if args[:5] == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
                return CommandResult(list(args), 0, stdout=next(status_outputs))
            return CommandResult(list(args), 0)

        before_status = _commit_message_worktree_status(config, runner)
        with pytest.raises(RuntimeError, match="commit-message drafting modified"):
            _handle_commit_message_side_effects(
                config,
                runner,
                6,
                before_status=before_status,
                timeout_seconds=None,
            )

        side_effects = json.loads(
            (artifact_dir / "commit-6-message-side-effects.json").read_text(encoding="utf-8")
        )
        assert side_effects["created_paths_removed"] == []
        assert side_effects["unsafe_status_lines"] == ["?? ../escape.txt"]
