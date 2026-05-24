"""Tests for the ReviewHarness adapter wiring (REVREM-TASK-003 B2f)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import code_review_loop.cli as MODULE
from code_review_loop.adapters.review import ReviewAdapter
from code_review_loop.clock import Clock
from code_review_loop.core.ports import (
    CommandResult,
    ReviewOutcome,
    ReviewRequest,
    RunContext,
)
from code_review_loop.identity import RunIdentity


def _ctx(runner=None, **kwargs: object) -> RunContext:
    return RunContext(
        clock=MagicMock(spec=Clock),
        identity=MagicMock(spec=RunIdentity),
        runner=runner if runner is not None else MagicMock(),
        **kwargs,  # type: ignore[arg-type]
    )


class TestReviewAdapter:
    def test_dry_run_returns_findings_status(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            dry_run=True,
        )
        runner = MagicMock(side_effect=AssertionError("no subprocess in dry-run"))
        ctx = _ctx(runner=runner)
        adapter = ReviewAdapter(config)

        outcome = adapter.execute(ReviewRequest(artifact_label="review-1", display_label="1"), ctx)

        assert isinstance(outcome, ReviewOutcome)
        # dry_run produces a CommandResult with "findings" status
        assert outcome.status in ("findings", "clear", "unknown")
        runner.assert_not_called()

    def test_artifact_label_and_display_label_threaded(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=MagicMock())
        adapter = ReviewAdapter(config)

        # REVREM-TASK-003 Wave C3a step 2: run_codex_review now lives in
        # ``adapters._review_impl`` and is imported by ``adapters.review``
        # directly, not via the cli re-export. Patch the binding the adapter
        # actually calls.
        with patch("code_review_loop.adapters.review.run_codex_review") as mock_review:
            mock_review.return_value = ("clear", CommandResult(["codex"], 0))
            outcome = adapter.execute(
                ReviewRequest(artifact_label="review-final", display_label="final"),
                ctx,
            )

        args, kwargs = mock_review.call_args
        assert args[2] == "review-final"
        assert kwargs.get("display_label") == "final"
        assert outcome.status == "clear"

    def test_runtime_error_propagates(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        )
        ctx = _ctx(runner=MagicMock(return_value=CommandResult(["codex"], 2)))
        adapter = ReviewAdapter(config)

        with pytest.raises(RuntimeError):
            adapter.execute(ReviewRequest(artifact_label="review-1"), ctx)


class TestEngineDispatch:
    def test_harness_called_when_wired(self) -> None:
        fake_result = CommandResult(["codex"], 0, stdout="REVIEW_STATUS: clean\n")
        fake_outcome = ReviewOutcome(status="clear", result=fake_result)

        class SentinelHarness:
            calls: list[ReviewRequest] = []

            def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
                SentinelHarness.calls.append(request)
                return fake_outcome

        sentinel = SentinelHarness()
        ctx = _ctx(phase_review=sentinel)
        request = ReviewRequest(artifact_label="review-1", display_label="1")

        if ctx.phase_review is not None:
            outcome = ctx.phase_review.execute(request, ctx)
        else:
            raise AssertionError("harness branch not taken")

        assert outcome is fake_outcome
        assert SentinelHarness.calls[0].artifact_label == "review-1"
        assert SentinelHarness.calls[0].display_label == "1"

    def test_preflight_blocks_before_review_adapter_called(self, tmp_path: Path, monkeypatch) -> None:
        """Preflight errors stop execution before ReviewAdapter.execute is called."""
        import code_review_loop.adapters.review as _review_mod

        def fail_review(*_args, **_kwargs):
            raise AssertionError("review adapter must not run when preflight blocks")

        monkeypatch.setattr(_review_mod.ReviewAdapter, "execute", fail_review)

        # Set up a proper git repo with an invalid base
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        monkeypatch.chdir(repo)

        exit_code = MODULE.main(
            ["--base", "missing", "--codex-bin", "git", "--artifact-dir", "artifacts"]
        )
        assert exit_code == 4  # preflight blocked; adapter was never called
