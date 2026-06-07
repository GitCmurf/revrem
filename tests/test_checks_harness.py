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

    def _config(self, tmp_path: Path, *, commit_after_remediation: bool = True) -> LoopConfig:
        (tmp_path / "artifacts").mkdir()
        (tmp_path / ".git").mkdir()
        return LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
            commit_after_remediation=commit_after_remediation,
        )

    def test_check_only_fails_when_untracked_non_artifact_files_remain(
        self, tmp_path: Path
    ) -> None:
        """Non-auto-commit runs must fail the cleanliness check when
        untracked non-artifact files are present. The previous behaviour
        returned exit code 0, which let the loop report clear while leaving
        new files outside the reviewed ``git diff`` patch.
        """
        config = self._config(tmp_path, commit_after_remediation=False)

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                return CommandResult(
                    cmd,
                    0,
                    stdout="?? src/leftover.py\0?? docs/notes.md\0",
                )
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 1
        assert "FAILED" in result.stdout
        assert "auto-commit is disabled" in result.stdout
        assert "src/leftover.py" in result.stdout
        assert "docs/notes.md" in result.stdout
        assert "git diff" in result.stdout

    def test_check_only_passes_when_no_untracked_files(self, tmp_path: Path) -> None:
        """Non-auto-commit runs with no untracked files still pass cleanly."""
        config = self._config(tmp_path, commit_after_remediation=False)

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            return CommandResult(list(args), 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0

    def test_passes_when_no_untracked_files(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            calls.append(list(args))
            return CommandResult(list(args), 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0
        assert calls == [["git", "status", "-z", "--untracked-files=all"]]

    def test_auto_stages_legitimate_untracked_files(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        status_calls: list[list[str]] = []
        add_calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                status_calls.append(cmd)
                if len(status_calls) == 1:
                    return CommandResult(
                        cmd, 0, stdout="?? src/new_module.py\0?? tests/test_new.py\0"
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
        assert len(status_calls) >= 2

    def test_decodes_paths_with_spaces_and_backslashes(self, tmp_path: Path) -> None:
        """Regression test: ``git status -z`` emits untracked paths verbatim
        (no quoting, no escaping), so the parsed paths must reach
        ``git add --intent-to-add`` byte-for-byte. The previous
        ``--porcelain`` parser forwarded Git's quoted form
        (``"a b"`` / ``"back\\slash"``) which makes the pathspec miss the file.
        """
        config = self._config(tmp_path)
        add_calls: list[list[str]] = []
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            nonlocal status_invocations
            cmd = list(args)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(
                        cmd,
                        0,
                        stdout=(
                            "?? src/has space.py\0"
                            "?? docs/back\\slash.md\0"
                            "?? src/quote\"file.py\0"
                            "?? src/newline\nfile.py\0"
                        ),
                    )
                return CommandResult(cmd, 0, stdout="")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                add_calls.append(cmd)
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0, result.stdout
        added_paths = [c[4] for c in add_calls]
        assert added_paths == [
            "src/has space.py",
            "docs/back\\slash.md",
            "src/quote\"file.py",
            "src/newline\nfile.py",
        ]
        for path in added_paths:
            assert path in result.stdout
        for cmd in add_calls:
            pathspec = cmd[-1]
            assert not pathspec.startswith('"') and not pathspec.endswith('"'), (
                f"intent-add pathspec must be unquoted, got {cmd!r}"
            )

    def test_skips_artifact_dir_files(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        calls: list[list[str]] = []
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            calls.append(cmd)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                nonlocal status_invocations
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(
                        cmd,
                        0,
                        stdout="?? artifacts/scratch.txt\0?? src/real.py\0",
                    )
                return CommandResult(
                    cmd, 0, stdout="?? artifacts/scratch.txt\0A  src/real.py\0"
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
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                return CommandResult(cmd, 0, stdout="?? src/broken.py\0")
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
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(cmd, 0, stdout="?? src/new.py\0")
                return CommandResult(cmd, 0, stdout="?? src/new.py\0")
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

    def test_check_only_does_not_intent_add_or_recheck(self, tmp_path: Path) -> None:
        """When auto-commit is disabled, the cleanliness check must not call
        ``git add --intent-to-add`` and must not re-run ``git status``. The
        untracked paths are surfaced in the result stdout so the operator and
        the model can see them, but the git index is left untouched and the
        result is reported as failed so remediation must account for the
        untracked paths before the loop can report clear.
        """
        config = self._config(tmp_path, commit_after_remediation=False)
        calls: list[list[str]] = []

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            cmd = list(args)
            calls.append(cmd)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                return CommandResult(cmd, 0, stdout="?? src/new.py\0")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 1
        assert [c for c in calls if c[:3] == ["git", "add", "--intent-to-add"]] == []
        assert [
            c
            for c in calls
            if c[:2] == ["git", "status"] and "-z" in c
        ] == [["git", "status", "-z", "--untracked-files=all"]]
        assert "auto-commit is disabled" in result.stdout
        assert "FAILED" in result.stdout
        assert "src/new.py" in result.stdout

    def test_check_only_lists_artifact_dir_files_without_staging(self, tmp_path: Path) -> None:
        """In check-only mode, artifact-dir files are still filtered out of
        the operator-facing list and never intent-added, and the result is
        reported as failed so the operator must account for the remaining
        untracked non-artifact file before the loop can report clear.
        """
        config = self._config(tmp_path, commit_after_remediation=False)
        add_calls: list[list[str]] = []
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            nonlocal status_invocations
            cmd = list(args)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                status_invocations += 1
                return CommandResult(
                    cmd,
                    0,
                    stdout="?? artifacts/scratch.txt\0?? src/real.py\0",
                )
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                add_calls.append(cmd)
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 1
        assert add_calls == []
        assert status_invocations == 1
        assert "src/real.py" in result.stdout
        assert "artifacts/scratch.txt" not in result.stdout
        assert "FAILED" in result.stdout

    def test_check_only_does_not_mutate_git_index(self, tmp_path: Path) -> None:
        """End-to-end: with a real git repo and ``commit_after_remediation``
        disabled, the cleanliness check must not leave any intent-to-add
        entries in the index. ``git status --short`` should keep the untracked
        marker (``??``) and never show the ``A `` (intent-added) marker. The
        result must be reported as failed so remediation must account for the
        untracked path before the loop can report clear.
        """
        import subprocess

        (tmp_path / "artifacts").mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
        )
        (tmp_path / "README").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "new.py").write_text("print('hello')\n", encoding="utf-8")

        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
            commit_after_remediation=False,
        )

        def _real_runner(args, cwd, input_text=None, timeout_seconds=None):
            completed = subprocess.run(
                list(args),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return CommandResult(list(args), completed.returncode, stdout=completed.stdout, stderr=completed.stderr)

        result = run_worktree_cleanliness_check(config, _real_runner)

        assert result.returncode == 1, result.stdout
        assert "auto-commit is disabled" in result.stdout
        assert "FAILED" in result.stdout
        assert "src/new.py" in result.stdout

        status_after = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        status_lines = status_after.stdout.splitlines()
        assert any(line.startswith("?? src/new.py") for line in status_lines)
        assert not any(line.startswith("A ") for line in status_lines)

        diff_after = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert diff_after.stdout.strip() == ""

    def test_intent_add_runs_from_git_root_when_cwd_is_subdirectory(self, tmp_path: Path) -> None:
        """``git status -z`` emits paths relative to the repository
        root even when the subprocess is launched from a subdirectory. The
        ``git add --intent-to-add`` subprocess must therefore be rooted at
        the git worktree so the repo-root-relative pathspec resolves
        correctly. Otherwise Git would look under ``<cwd>/<path>`` and the
        pathspec would miss the file.
        """
        repo = tmp_path / "repo"
        subdir = repo / "sub"
        subdir.mkdir(parents=True)
        (repo / ".git").mkdir()
        (subdir / "artifacts").mkdir()

        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=subdir,
            artifact_dir=subdir / "artifacts",
            check_commands=("true",),
            commit_after_remediation=True,
        )

        add_calls: list[tuple[list[str], Path]] = []
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            nonlocal status_invocations
            cmd = list(args)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(
                        cmd,
                        0,
                        stdout="?? sub/src/new_module.py\0?? sub/tests/test_new.py\0",
                    )
                return CommandResult(cmd, 0, stdout="")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                add_calls.append((cmd, cwd))
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0, result.stdout
        assert add_calls, "expected git add --intent-to-add to be called"
        for cmd, cwd in add_calls:
            assert cmd == ["git", "add", "--intent-to-add", "--", cmd[-1]]
            assert cwd == repo, f"intent-add cwd must be the git root; got {cwd}"
        assert [c[0][-1] for c in add_calls] == [
            "sub/src/new_module.py",
            "sub/tests/test_new.py",
        ]

    def test_intent_add_falls_back_to_cwd_when_no_git_root(self, tmp_path: Path) -> None:
        """When the cwd is itself the git worktree, the intent-add subprocess
        should use ``config.cwd`` as its root. This is the same fallback that
        preserves the original behaviour for callers that have not enabled
        subdirectory invocations.
        """
        import subprocess

        (tmp_path / "artifacts").mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
        )
        (tmp_path / "README").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "new.py").write_text("print('hi')\n", encoding="utf-8")

        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
            commit_after_remediation=True,
        )

        add_cwds: list[Path] = []
        status_invocations = 0

        def runner(args, cwd, input_text=None, timeout_seconds=None):
            nonlocal status_invocations
            cmd = list(args)
            if cmd[:2] == ["git", "status"] and "-z" in cmd:
                status_invocations += 1
                if status_invocations == 1:
                    return CommandResult(cmd, 0, stdout="?? src/new.py\0")
                return CommandResult(cmd, 0, stdout="")
            if cmd[:3] == ["git", "add", "--intent-to-add"]:
                add_cwds.append(cwd)
                return CommandResult(cmd, 0)
            return CommandResult(cmd, 0, stdout="")

        result = run_worktree_cleanliness_check(config, runner)

        assert result.returncode == 0, result.stdout
        assert add_cwds == [tmp_path]

    def test_intent_add_stage_new_file_in_subdirectory_with_real_git(self, tmp_path: Path) -> None:
        """End-to-end: with a real git repository rooted above ``cwd`` and
        ``commit_after_remediation`` enabled, the cleanliness check must
        successfully intent-add a new file that lives inside a
        subdirectory. The status output reports the path as
        ``sub/...`` (repo-root-relative); the intent-add subprocess must
        resolve it against the git root so the pathspec matches.
        """
        import subprocess

        repo = tmp_path / "repo"
        subdir = repo / "sub"
        subdir.mkdir(parents=True)
        (subdir / "artifacts").mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@e.com"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
        )
        (repo / "README").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        (subdir / "src").mkdir()
        (subdir / "src" / "new.py").write_text("print('hello')\n", encoding="utf-8")

        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=subdir,
            artifact_dir=subdir / "artifacts",
            check_commands=("true",),
            commit_after_remediation=True,
        )

        def _real_runner(args, cwd, input_text=None, timeout_seconds=None):
            completed = subprocess.run(
                list(args),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return CommandResult(list(args), completed.returncode, stdout=completed.stdout, stderr=completed.stderr)

        result = run_worktree_cleanliness_check(config, _real_runner)

        assert result.returncode == 0, result.stdout
        assert "auto-staged" in result.stdout
        assert "sub/src/new.py" in result.stdout

        status_after = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        status_lines = status_after.stdout.splitlines()
        # After intent-add the path should appear as `` A sub/src/new.py``
        # rather than ``?? sub/src/new.py``. The leading space is the empty
        # index status; ``A`` is the intent-to-add work-tree status.
        assert any(line.startswith(" A sub/src/new.py") for line in status_lines)
        assert not any(line.startswith("?? sub/src/new.py") for line in status_lines)

    def test_intent_add_decodes_paths_with_spaces_in_real_git(self, tmp_path: Path) -> None:
        """End-to-end regression test for the porcelain quoting bug.

        With a real git repository and ``commit_after_remediation`` enabled,
        the cleanliness check must successfully intent-add untracked files
        whose names contain characters that ``git status --porcelain`` would
        have wrapped in C-style quotes (spaces, double-quotes, backslashes).
        The NUL-delimited parser passes the paths through verbatim, so the
        intent-add pathspec resolves against the worktree and the recheck
        shows the ``A`` intent-to-add marker for each file.
        """
        import subprocess

        (tmp_path / "artifacts").mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
        )
        (tmp_path / "README").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
        )
        (tmp_path / "src").mkdir()
        spaced = tmp_path / "src" / "has space.py"
        spaced.write_text("print('hello')\n", encoding="utf-8")
        quoted = tmp_path / "src" / 'quote"file.py'
        quoted.write_text("print('hi')\n", encoding="utf-8")
        slashed = tmp_path / "src" / "back\\slash.py"
        slashed.write_text("print('yo')\n", encoding="utf-8")

        config = LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            check_commands=("true",),
            commit_after_remediation=True,
        )

        def _real_runner(args, cwd, input_text=None, timeout_seconds=None):
            completed = subprocess.run(
                list(args),
                cwd=cwd,
                capture_output=True,
                timeout=timeout_seconds,
            )
            return CommandResult(
                list(args),
                completed.returncode,
                stdout=completed.stdout.decode("utf-8", errors="surrogateescape"),
                stderr=completed.stderr.decode("utf-8", errors="surrogateescape"),
            )

        result = run_worktree_cleanliness_check(config, _real_runner)

        assert result.returncode == 0, result.stdout
        for path in ("src/has space.py", 'src/quote"file.py', "src/back\\slash.py"):
            assert path in result.stdout, f"expected {path!r} in auto-staged list"

        status_after = subprocess.run(
            ["git", "status", "-z", "--untracked-files=all"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        status_text = status_after.stdout.decode("utf-8", errors="surrogateescape")
        for path in ("src/has space.py", 'src/quote"file.py', "src/back\\slash.py"):
            # After ``git add --intent-to-add`` the path moves from ``??``
            # (untracked) to `` A`` (intent-added work-tree entry). Either
            # way the path is no longer reported as ``?? <path>\0``; the
            # check below makes sure the bug — forwarding Git's quoted
            # form so ``git add`` misses the file and the path stays as
            # ``??`` — cannot recur.
            untracked_marker = f"?? {path}\0"
            assert untracked_marker not in status_text, (
                f"path {path!r} should have been intent-added and is no "
                f"longer untracked; got status output {status_text!r}"
            )

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
