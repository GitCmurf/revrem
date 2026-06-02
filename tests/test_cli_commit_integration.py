from __future__ import annotations

import json
from pathlib import Path

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop.adapters import checks as checks_impl
from code_review_loop.adapters import commit as commit_impl
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RunContext
from code_review_loop.runtime import RunLoopFailed
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs


def make_git_worktree(
    tmp_path: Path, cwd_rel: str | None = "work"
) -> tuple[Path, Path]:
    (tmp_path / ".git").mkdir(exist_ok=True)
    cwd = tmp_path if cwd_rel is None else tmp_path / cwd_rel
    cwd.mkdir(parents=True, exist_ok=True)
    return tmp_path, cwd


def make_run_context(runner) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )


def git_repo_root_result(args, cwd: Path, repo_root: Path) -> CommandResult | None:
    if list(args) == ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]:
        return CommandResult(list(args), 0, stdout=f"{repo_root}\n")
    return None


def test_loop_commits_after_passing_checks(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if (result := git_repo_root_result(args, cwd, repo_root)) is not None:
            return result
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return CommandResult(list(args), 0, stdout="1 passed\n")
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"] and "--stat" in args:
            return CommandResult(list(args), 0, stdout=" src/code.py | 2 +-\n")
        if args[:3] == ["git", "diff", "--cached"] and "--name-only" in args:
            return CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[0:2] == ["codex", "exec"] and "--sandbox" in args:
            return CommandResult(
                list(args), 0, stdout="fix(cli): harden RevRem commit flow\n"
            )
        if args[:3] == ["git", "commit", "-m"]:
            return CommandResult(
                list(args),
                0,
                stdout="[branch abc] fix(cli): harden RevRem commit flow\n",
            )
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        commit_after_remediation=True,
        commit_message_model="gpt-5.3-codex-spark",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    commands = [call[0] for call in calls]
    assert ["git", "add", "-A"] in commands
    assert ["git", "-C", str(repo_root), "reset", "--", "artifacts"] in commands
    assert [
        "git",
        "commit",
        "-m",
        "fix(cli): harden RevRem commit flow (RevRem)",
    ] in commands
    assert any(
        command[:8]
        == [
            "codex",
            "exec",
            "-c",
            'web_search="disabled"',
            "--sandbox",
            "read-only",
            "--color",
            "never",
        ]
        for command in commands
    )
    assert summary["iterations"][0]["commit_status"] == "committed"
    assert set(summary["artifact_paths"]["commits"]) == {
        str(tmp_path / "artifacts" / "commit-1-add.txt"),
        str(tmp_path / "artifacts" / "commit-1-reset-artifacts.txt"),
        str(tmp_path / "artifacts" / "commit-1-message-draft.txt"),
        str(tmp_path / "artifacts" / "commit-1.txt"),
        str(tmp_path / "artifacts" / "commit-1-message.txt"),
    }
    commit_prompt = next(
        input_text
        for command, input_text, _timeout in calls
        if command[:8]
        == [
            "codex",
            "exec",
            "-c",
            'web_search="disabled"',
            "--sandbox",
            "read-only",
            "--color",
            "never",
        ]
    )
    assert commit_prompt is not None and "Files:" in commit_prompt
    assert "Conventional Commit" in commit_prompt
    assert "(RevRem)" in commit_prompt


def test_git_staging_commands_for_commit_reset_relative_artifact_dir(tmp_path):
    repo_root, cwd = make_git_worktree(tmp_path)
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=Path("../artifacts/revrem"),
    )

    assert commit_impl.git_add_command_for_commit(config) == ["git", "add", "-A"]
    assert commit_impl.git_add_command_for_commit(config) == ["git", "add", "-A"]
    assert commit_impl.git_reset_artifact_command_for_commit(config, repo_root) == [
        "git",
        "-C",
        str(repo_root),
        "reset",
        "--",
        "artifacts/revrem",
    ]


def test_git_staging_commands_skip_relative_artifact_dir_outside_cwd(tmp_path):
    _repo_root, cwd = make_git_worktree(tmp_path)
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=Path("../../revrem-artifacts"),
    )

    assert commit_impl.git_add_command_for_commit(config) == ["git", "add", "-A"]
    assert commit_impl.git_reset_artifact_command_for_commit(config, _repo_root) is None


def test_run_commit_refuses_repo_root_artifact_dir_before_staging(tmp_path):
    calls = []
    make_git_worktree(tmp_path, cwd_rel=None)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:5] == ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"]:
            return CommandResult(list(args), 0, stdout=f"{tmp_path}\n")
        return CommandResult(list(args), 0, stdout="unexpected\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=Path("."),
        commit_after_remediation=True,
    )

    with pytest.raises(
        RuntimeError, match="artifact-dir resolves to the repository root"
    ):
        commit_impl.run_commit(config, runner, 1, ctx=make_run_context(runner))

    assert calls == [
        (
            ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
            None,
            300,
        )
    ]


def test_loop_skips_commit_when_checks_fail(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return CommandResult(list(args), 1, stdout="1 failed\n")
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        commit_after_remediation=True,
        commit_message_model="gpt-5.3-codex-spark",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["iterations"][0]["check_failures"] == 1
    assert "commit_status" not in summary["iterations"][0]
    assert [
        command for command, _input_text, _timeout in calls if command[0] == "git"
    ] == [["git", "status", "--porcelain=v1", "--untracked-files=all"]]


def test_pytest_check_is_skipped_for_typescript_repo_without_python_surface(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest"}}\n', encoding="utf-8"
    )
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        raise AssertionError("pytest should be skipped before subprocess execution")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
    )

    results, _failed = checks_impl.run_checks(
        config, runner, 1, make_run_context(runner)
    )

    assert calls == []
    assert results[0].returncode == 0

    assert "appears to be non-Python" in results[0].stdout
    assert "SKIPPED adaptive check" in (
        tmp_path / "artifacts" / "check-1-1.txt"
    ).read_text(encoding="utf-8")


def test_pytest_check_is_skipped_for_typescript_repo_with_incidental_python_file(
    tmp_path,
):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest"}}\n', encoding="utf-8"
    )
    (tmp_path / "helper.py").write_text("print('helper')\n", encoding="utf-8")
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        raise AssertionError("pytest should be skipped before subprocess execution")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
    )

    results, _failed = checks_impl.run_checks(
        config, runner, 1, make_run_context(runner)
    )

    assert calls == []
    assert results[0].returncode == 0

    assert "appears to be non-Python" in results[0].stdout


@pytest.mark.parametrize("returncode", [4, 5])
def test_pytest_in_typescript_repo_is_normalized_when_subprocess_returns_non_python_codes(
    tmp_path,
    returncode,
):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest"}}\n', encoding="utf-8"
    )
    command = ["pytest", "-q"]
    result = CommandResult(
        command, returncode, stdout="pytest output\n", stderr="pytest error\n"
    )

    normalized = checks_impl.normalize_adaptive_check_result(command, tmp_path, result)

    assert normalized.returncode == 0
    assert f"pytest exited {returncode}" in normalized.stdout
    assert "pytest output" in normalized.stdout
    assert "pytest error" in normalized.stdout


def test_pytest_interrupt_is_preserved_for_typescript_repo(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest"}}\n', encoding="utf-8"
    )
    command = ["pytest", "-q"]
    result = CommandResult(command, 2, stdout="interrupted\n")

    assert (
        checks_impl.normalize_adaptive_check_result(command, tmp_path, result) is result
    )


def test_pytest_failure_is_preserved_for_python_repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )
    command = ["pytest", "-q"]
    result = CommandResult(command, 5, stdout="no tests ran\n")

    assert checks_impl.adaptive_check_skip_reason(command, tmp_path) is None
    assert (
        checks_impl.normalize_adaptive_check_result(command, tmp_path, result) is result
    )


def test_loop_refuses_to_auto_commit_from_dirty_worktree(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(
                list(args),
                0,
                stdout=" M src/other.py\n?? notes.txt\n",
            )
        raise AssertionError(f"unexpected command: {args!r}")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
    )

    with pytest.raises(RuntimeError) as excinfo:
        runner_mod.run_loop(config, runner)

    assert "--commit-after-remediation" in str(excinfo.value)
    assert "src/other.py" in str(excinfo.value)
    assert "notes.txt" in str(excinfo.value)
    assert [command for command, _input_text, _timeout in calls] == [
        ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    ]


def test_loop_stops_after_unknown_review_when_remediation_has_no_staged_changes(
    tmp_path,
):
    calls = []
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return CommandResult(
                list(args), 0, stdout="The implementation appears sound.\n"
            )
        if args[0] == "pytest":
            return CommandResult(list(args), 0, stdout="1 passed\n")
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 0)
        return CommandResult(list(args), 0, stdout="No edits were needed.\n")

    config = LoopConfig(
        base="main",
        max_iterations=3,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        commit_after_remediation=True,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    review_calls = [
        command
        for command, _input_text, _timeout in calls
        if command[0] == "codex" and "review" in command
    ]
    assert len(review_calls) == 1
    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "no_changes_after_remediation"
    assert summary["iterations"][0]["review_status"] == "unknown"
    assert summary["iterations"][0]["commit_status"] == "skipped_no_changes"


def test_loop_writes_failure_summary_when_commit_fails(tmp_path):
    review_outputs = iter(["Full review comments:\n\n- [P2] Fix profile merge\n"])
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if (result := git_repo_root_result(args, cwd, repo_root)) is not None:
            return result
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return CommandResult(list(args), 1, stderr="nothing to commit\n")
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
    )

    with pytest.raises(RunLoopFailed):
        runner_mod.run_loop(config, runner)

    summary = json.loads(
        (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "commit_failed"
    assert summary["iterations"][0]["commit_failed"] is True
    assert (
        str(tmp_path / "artifacts" / "commit-1.txt")
        in summary["artifact_paths"]["commits"]
    )


def test_loop_remediates_commit_hook_failure_by_default(tmp_path):
    calls = []
    remediation_prompts = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "Full review comments:\n\n- [P2] Fix commit-hook mypy failure\n",
        ]
    )
    commit_attempts = 0
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal commit_attempts
        calls.append((list(args), input_text, timeout_seconds))
        if (result := git_repo_root_result(args, cwd, repo_root)) is not None:
            return result
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0:2] == ["codex", "exec"]:
            remediation_prompts.append(input_text or "")
            return CommandResult(list(args), 0, stdout="remediated\n")
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            commit_attempts += 1
            if commit_attempts == 1:
                return CommandResult(
                    list(args),
                    1,
                    stdout=(
                        "Running mypy on staged Python files...\n"
                        "tests/unit/test_loop.py:195: error: Module has no attribute\n"
                        "Found 1 error in 1 file\n"
                    ),
                )
            return CommandResult(list(args), 0, stdout="[branch abc] fix\n")
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["iterations"][0]["commit_status"] == "hook_failed"
    assert summary["iterations"][0]["commit_failed"] is True
    assert summary["iterations"][1]["commit_status"] == "committed"
    assert summary["pending_check_failures"] is False
    assert summary["commit_on_hook_failure"] == "remediate"
    assert summary["commit_no_verify"] is False
    assert "Commit hook failure" in remediation_prompts[1]
    assert "Running mypy on staged Python files" in remediation_prompts[1]
    assert (
        str(tmp_path / "artifacts" / "commit-1.txt")
        in summary["artifact_paths"]["commits"]
    )


def test_loop_stops_on_commit_hook_failure_when_policy_is_stop(tmp_path):
    review_outputs = iter(["Full review comments:\n\n- [P2] Fix profile merge\n"])
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if (result := git_repo_root_result(args, cwd, repo_root)) is not None:
            return result
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return CommandResult(
                list(args),
                1,
                stderr="pre-commit hook failed: mypy found 1 error\n",
            )
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
        commit_on_hook_failure="stop",
    )

    with pytest.raises(RunLoopFailed):
        runner_mod.run_loop(config, runner)

    summary = json.loads(
        (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["stopped_reason"] == "commit_hook_failed"
    assert summary["staged_changes_left"] is True
    assert summary["pending_check_failures"] is True
    assert summary["iterations"][0]["commit_status"] == "hook_failed"


def test_run_commit_uses_no_verify_only_on_retry(tmp_path):
    calls = []
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if (result := git_repo_root_result(args, cwd, repo_root)) is not None:
            return result
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "--no-verify"]:
            return CommandResult(list(args), 0, stdout="[branch abc] fix\n")
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
        commit_on_hook_failure="no-verify",
    )

    assert (
        commit_impl.run_commit(config, runner, 1, ctx=make_run_context(runner))
        == "committed"
    )
    assert ["git", "commit", "-m", "chore(code): update code in src (RevRem)"] in calls
    assert [
        "git",
        "commit",
        "--no-verify",
        "-m",
        "chore(code): update code in src (RevRem)",
    ] not in calls

    calls.clear()
    assert (
        commit_impl.run_commit(
            config, runner, 1, ctx=make_run_context(runner), retrying=True
        )
        == "committed"
    )
    assert [
        "git",
        "commit",
        "--no-verify",
        "-m",
        "chore(code): update code in src (RevRem)",
    ] in calls
