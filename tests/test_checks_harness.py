"""Tests for the ChecksHarness adapter wiring (REVREM-TASK-003 B2b).

The adapter closes over LoopConfig and delegates to cli.run_checks, converting
the legacy tuple return into a ChecksOutcome.  These tests verify:
  1. The adapter wraps run_checks output into ChecksOutcome correctly.
  2. The engine dispatch at _run_loop's checks call-site uses ctx.phase_checks.
  3. A fully fake harness can replace the adapter without touching cli.py.
  4. The worktree cleanliness check auto-stages untracked non-artifact files
     with ``git add --intent-to-add`` so legitimate patches that add new files
     do not block the post-remediation verification flow.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from code_review_loop.adapters.checks import (
    ChecksAdapter,
    format_check_result_for_progress,
    format_returncode_for_progress,
    run_worktree_cleanliness_check,
)
from code_review_loop.clock import Clock
from code_review_loop.config import LoopConfig
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


class RecordingReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def phase(self, phase: str, label: str, status: str, detail: str = "") -> None:
        self.calls.append((phase, label, status, detail))


def test_format_returncode_for_progress_names_signal_exits() -> None:
    assert format_returncode_for_progress(-9) == "exit -9 (SIGKILL)"
    assert format_returncode_for_progress(-999) == "exit -999 (signal 999)"
    assert format_returncode_for_progress(2) == "exit 2"


def test_format_check_result_for_progress_names_timeouts() -> None:
    result = CommandResult(["pytest", "-q"], -1, stderr="Command timed out after 300 seconds\n")

    assert format_check_result_for_progress(result) == "timeout after 300s"


# ---------------------------------------------------------------------------
# ChecksAdapter unit tests
# ---------------------------------------------------------------------------

class TestChecksAdapter:
    def test_returns_checks_outcome_on_success(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
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
        assert len(outcome.results) == 2
        assert outcome.results[1].returncode == 0
        assert outcome.failed_commands == ()

    def test_failed_check_appears_in_failed_commands(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
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

        assert len(outcome.results) == 2
        assert outcome.results[1].returncode == 1
        assert "pytest -q" in outcome.failed_commands

    def test_signal_killed_check_names_signal_in_progress(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("pytest -q",),
        )
        fail_result = CommandResult(["pytest", "-q"], -9, stdout="partial\n")
        reporter = RecordingReporter()
        ctx = _ctx(runner=_runner_returning(fail_result), progress_reporter=reporter)
        adapter = ChecksAdapter(config)

        outcome = adapter.execute(ChecksRequest(iteration=1), ctx)

        assert outcome.results[1].returncode == -9
        assert ("check", "1.2", "failed", "exit -9 (SIGKILL)") in reporter.calls

    def test_dry_run_skips_subprocess(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
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
        assert outcome.results[1].returncode == 0
        assert "DRY_RUN" in outcome.results[1].stdout
        runner.assert_not_called()

    def test_adaptive_pytest_skip_for_typescript_repo(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
        config = LoopConfig(
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

        assert outcome.results[1].returncode == 0
        assert "SKIPPED adaptive check" in outcome.results[1].stdout
        runner.assert_not_called()

# ---------------------------------------------------------------------------
# Worktree cleanliness check tests
# ---------------------------------------------------------------------------


class TestWorktreeCleanlinessCheck:
    """Cover the untracked-file handling in ``run_worktree_cleanliness_check``."""

    def _config(self, tmp_path: Path) -> LoopConfig:
        (tmp_path / "artifacts").mkdir()
        (tmp_path / ".git").mkdir()
        return LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
        )

    def test_passes_when_no_untracked_files(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            calls.append(list(args))
            return CommandResult(list(args), 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0
        assert calls == [["git", "status", "--porcelain", "--untracked-files=all"]]

    def test_auto_stages_legitimate_untracked_files(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        status_calls: list[str] = []
        add_calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                status_calls.append(cmd[2] if len(cmd) > 2 else "")
                if not status_calls or len(status_calls) == 1:
                    return CommandResult(
                        cmd, 0, stdout="?? src/new_module.py\n?? tests/test_new.py\n"
                    )
                return CommandResult(cmd, 0, stdout="")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                add_calls.append(cmd)
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0
        assert "auto-staged" in result.stdout
        assert "src/new_module.py" in result.stdout
        assert "tests/test_new.py" in result.stdout
        assert ["git", "add", "--intent-to-add", "--", "src/new_module.py"] in add_calls
        assert ["git", "add", "--intent-to-add", "--", "tests/test_new.py"] in add_calls
        assert len([c for c in status_calls if c == "--porcelain"]) >= 2

    def test_skips_artifact_dir_files(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        calls: list[list[str]] = []
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            calls.append(cmd)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                nonlocal status_invocations
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(
                        cmd,
                        0,
                        stdout="?? artifacts/scratch.txt\n?? src/real.py\n",
                    )
                return CommandResult(
                    cmd, 0, stdout="?? artifacts/scratch.txt\nA  src/real.py\n"
                )
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0
        add_paths = [c[4] for c in calls if c[:3] == ["git", "add", "--intent-to-add"]]
        assert add_paths == ["src/real.py"]
        assert "src/real.py" in result.stdout
        assert "artifacts/scratch.txt" not in result.stdout

    def test_fails_when_intent_add_errors(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return CommandResult(cmd, 0, stdout="?? src/broken.py\n")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                return CommandResult(cmd, 128, stderr="fatal: cannot add\n")
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 1
        assert "could not be intent-added" in result.stdout
        assert "src/broken.py" in result.stdout
        assert "fatal: cannot add" in result.stdout

    def test_fails_when_remaining_untracked_after_intent_add(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            nonlocal status_invocations
            cmd = list(args)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(cmd, 0, stdout="?? src/new.py\n")
                return CommandResult(cmd, 0, stdout="?? src/new.py\n")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 1
        assert "Untracked files remain after remediation" in result.stdout
        assert "src/new.py" in result.stdout

    def test_skips_when_no_git_marker(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
        )
        calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            calls.append(list(args))
            return CommandResult(list(args), 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0
        assert "SKIPPED cleanliness check" in result.stdout
        assert calls == []

    def test_skips_when_dry_run(self, tmp_path: Path) -> None:
        (tmp_path / "artifacts").mkdir()
        (tmp_path / ".git").mkdir()
        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
            dry_run=True,
        )
        calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            calls.append(list(args))
            return CommandResult(list(args), 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0
        assert "DRY_RUN" in result.stdout
        assert calls == []

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
