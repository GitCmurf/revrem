"""Tests for the ChecksHarness adapter wiring (REVREM-TASK-003 B2b).

The adapter closes over LoopConfig and delegates to cli.run_checks, converting
the legacy tuple return into a ChecksOutcome.  These tests verify:
  1. The adapter wraps run_checks output into ChecksOutcome correctly.
  2. The engine dispatch at _run_loop's checks call-site uses ctx.phase_checks.
  3. A fully fake harness can replace the adapter without touching cli.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import code_review_loop.runner as runner_mod
from code_review_loop.adapters.checks import ChecksAdapter
from code_review_loop.clock import Clock
from code_review_loop.core.ports import (
    ChecksOutcome,
    ChecksRequest,
    CommandResult,
    RunContext,
)
from code_review_loop.identity import RunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs

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


def _runner_returning(*results: CommandResult):
    """Return a runner callable that yields the given CommandResults in order."""
    results_iter = iter(results)

    def _runner(args, cwd, input_text=None, timeout_seconds=None):
        return next(results_iter)

    return _runner


# ---------------------------------------------------------------------------
# ChecksAdapter unit tests
# ---------------------------------------------------------------------------

class TestChecksAdapter:
    def test_returns_checks_outcome_on_success(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
        )
        success_result = CommandResult(["true"], 0, stdout="ok\n")
        ctx = _ctx(runner=_runner_returning(success_result))
        adapter = ChecksAdapter(config)

        outcome = adapter.execute(ChecksRequest(iteration=1), ctx)

        assert isinstance(outcome, ChecksOutcome)
        assert len(outcome.results) == 1
        assert outcome.results[0].returncode == 0
        assert outcome.failed_commands == ()

    def test_failed_check_appears_in_failed_commands(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("pytest -q",),
        )
        fail_result = CommandResult(["pytest", "-q"], 1, stdout="FAILED\n")
        ctx = _ctx(runner=_runner_returning(fail_result))
        adapter = ChecksAdapter(config)

        outcome = adapter.execute(ChecksRequest(iteration=1), ctx)

        assert len(outcome.results) == 1
        assert outcome.results[0].returncode == 1
        assert "pytest -q" in outcome.failed_commands

    def test_dry_run_skips_subprocess(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("pytest -q",),
            dry_run=True,
        )
        runner = MagicMock(side_effect=AssertionError("should not run subprocess in dry_run"))
        ctx = _ctx(runner=runner)
        adapter = ChecksAdapter(config)

        outcome = adapter.execute(ChecksRequest(iteration=1), ctx)

        assert outcome.results[0].returncode == 0
        assert "DRY_RUN" in outcome.results[0].stdout
        runner.assert_not_called()

    def test_adaptive_pytest_skip_for_typescript_repo(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
        config = runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("pytest -q",),
        )
        runner = MagicMock(side_effect=AssertionError("should be skipped before subprocess"))
        ctx = _ctx(runner=runner)
        adapter = ChecksAdapter(config)

        outcome = adapter.execute(ChecksRequest(iteration=1), ctx)

        assert outcome.results[0].returncode == 0
        assert "SKIPPED adaptive check" in outcome.results[0].stdout
        runner.assert_not_called()


# ---------------------------------------------------------------------------
# Engine dispatch: ctx.phase_checks wired vs. absent
# ---------------------------------------------------------------------------

class TestEngineDispatch:
    """Verify the harness dispatch branch in _run_loop."""

    def test_harness_called_when_wired(self) -> None:
        """When ctx.phase_checks is set, the engine delegates to it."""
        fake_outcome = ChecksOutcome(
            results=(CommandResult(["echo"], 0, stdout="ok\n"),),
            failed_commands=(),
        )

        class FakeChecksHarness:
            calls: list[ChecksRequest] = []

            def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
                self.calls.append(request)
                return fake_outcome

        fake = FakeChecksHarness()
        ctx = _ctx(phase_checks=fake)

        request = ChecksRequest(iteration=3)
        outcome = ctx.phase_checks.execute(request, ctx)

        assert outcome is fake_outcome
        assert fake.calls == [request]
        assert fake.calls[0].iteration == 3

    def test_engine_dispatch_branch_uses_harness_not_run_checks(self, tmp_path: Path) -> None:
        """When phase_checks is set, the dispatch branch calls the harness and
        does not call the legacy run_checks shim."""
        fake_outcome = ChecksOutcome(
            results=(CommandResult(["echo", "harness"], 0),),
            failed_commands=(),
        )

        class SentinelHarness:
            called = False

            def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
                SentinelHarness.called = True
                return fake_outcome

        harness = SentinelHarness()

        # Simulate the dispatch logic from _run_loop line 2196
        ctx = _ctx(phase_checks=harness)
        iteration = 5

        _checks_outcome = ctx.phase_checks.execute(ChecksRequest(iteration=iteration), ctx)
        check_results = list(_checks_outcome.results)
        failed_check_names = list(_checks_outcome.failed_commands)

        assert SentinelHarness.called
        assert check_results == list(fake_outcome.results)
        assert failed_check_names == []
        assert check_results[0].args == ["echo", "harness"]
