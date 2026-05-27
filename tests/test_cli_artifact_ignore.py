from __future__ import annotations

import re
from importlib import import_module

import pytest

import code_review_loop.runner as runner_mod
from code_review_loop.cli import config_builder
from code_review_loop.cli import config_support

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")



def test_default_artifact_dir_uses_revrem_namespace():
    artifact_dir = config_builder.default_artifact_dir()

    assert artifact_dir.parts[:2] == (".revrem", "runs")
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{32}", artifact_dir.name)


def test_profile_timeout_rejects_negative_values():
    with pytest.raises(ValueError, match="profile phase timeout must be non-negative"):
        config_builder.resolve_profile_timeout_seconds(-1)


def test_run_loop_creates_repo_local_revrem_gitignore_for_default_artifacts(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    runner_mod.run_loop(config, runner)
    runner_mod.ensure_default_artifact_ignore(config)

    assert (tmp_path / ".revrem" / ".gitignore").read_text(encoding="utf-8") == "runs/\n"


def test_run_loop_uses_git_info_exclude_for_default_artifacts_in_git_repo(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    git_info = tmp_path / ".git" / "info"
    git_info.mkdir(parents=True)
    (git_info / "exclude").write_text("# local excludes\n", encoding="utf-8")
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    runner_mod.run_loop(config, runner)

    assert (git_info / "exclude").read_text(encoding="utf-8") == "# local excludes\n.revrem/runs/\n"
    assert not (tmp_path / ".revrem" / ".gitignore").exists()


def test_run_loop_uses_repo_root_exclude_for_default_artifacts_from_subdirectory(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path / "repo"
    worktree = repo_root / "work"
    git_info = repo_root / ".git" / "info"
    git_info.mkdir(parents=True)
    (git_info / "exclude").write_text("# local excludes\n", encoding="utf-8")
    worktree.mkdir(parents=True)
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=worktree,
        artifact_dir=worktree / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    runner_mod.run_loop(config, runner)

    assert (git_info / "exclude").read_text(encoding="utf-8") == (
        "# local excludes\nwork/.revrem/runs/\n"
    )
    assert not (worktree / ".revrem" / ".gitignore").exists()


def test_run_loop_uses_common_exclude_for_default_artifacts_in_linked_worktree(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path / "repo"
    common_git_dir = repo_root / ".git"
    worktrees_dir = common_git_dir / "worktrees"
    linked_git_dir = worktrees_dir / "linked"
    linked_worktree = tmp_path / "linked"

    common_git_dir.mkdir(parents=True)
    (common_git_dir / "info").mkdir()
    (common_git_dir / "info" / "exclude").write_text("# local excludes\n", encoding="utf-8")
    linked_git_dir.mkdir(parents=True)
    linked_worktree.mkdir()
    (linked_worktree / ".git").write_text(
        f"gitdir: {linked_git_dir.as_posix()}\n",
        encoding="utf-8",
    )

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=linked_worktree,
        artifact_dir=linked_worktree / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    runner_mod.run_loop(config, runner)

    assert (common_git_dir / "info" / "exclude").read_text(encoding="utf-8") == (
        "# local excludes\n.revrem/runs/\n"
    )
    assert not (linked_worktree / ".revrem" / ".gitignore").exists()


def test_git_info_exclude_path_ignores_empty_gitdir_file(tmp_path):
    (tmp_path / ".git").write_text("gitdir:\n", encoding="utf-8")

    assert config_support.git_info_exclude_path(tmp_path) is None


def test_run_loop_appends_repo_root_exclude_when_existing_longer_entry_contains_substring(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path
    git_info = repo_root / ".git" / "info"
    git_info.mkdir(parents=True)
    (git_info / "exclude").write_text("work/.revrem/runs/\n", encoding="utf-8")
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=repo_root,
        artifact_dir=repo_root / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    runner_mod.run_loop(config, runner)

    assert (git_info / "exclude").read_text(encoding="utf-8") == (
        "work/.revrem/runs/\n.revrem/runs/\n"
    )


def test_run_loop_falls_back_to_workspace_gitignore_for_symlinked_default_artifacts(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path / "repo"
    repo_git_info = repo_root / ".git" / "info"
    repo_git_info.mkdir(parents=True)
    (repo_git_info / "exclude").write_text("# local excludes\n", encoding="utf-8")
    (repo_root / "nested").mkdir(parents=True)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    linked_cwd = workspace / "linked"
    linked_cwd.symlink_to(repo_root / "nested", target_is_directory=True)

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=linked_cwd,
        artifact_dir=linked_cwd / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    runner_mod.run_loop(config, runner)

    assert (workspace / "linked" / ".revrem" / ".gitignore").read_text(encoding="utf-8") == "runs/\n"
    assert (repo_git_info / "exclude").read_text(encoding="utf-8") == "# local excludes\n"

