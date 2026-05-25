from __future__ import annotations

import json
import os
import re
from importlib import import_module

import pytest

import code_review_loop.runner as runner_mod
from code_review_loop import application as application_mod
from code_review_loop import profiles
from code_review_loop.cli import args as cli_args
from code_review_loop.cli import config_builder
from code_review_loop.cli.commands import config as config_command

cli_main = import_module("code_review_loop.cli.main")


def test_main_resolves_latest_initial_review_from_custom_artifact_dir(tmp_path, monkeypatch):
    custom_root = tmp_path / "custom-artifacts"
    custom_run = custom_root / "20260428T010000Z"
    default_run = tmp_path / "tmp" / "code-review-loop" / "20260428T020000Z"
    custom_run.mkdir(parents=True)
    default_run.mkdir(parents=True)
    custom_review = custom_run / "review-final.txt"
    default_review = default_run / "review-final.txt"
    custom_review.write_text("custom", encoding="utf-8")
    default_review.write_text("default", encoding="utf-8")
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--initial-review-file",
            "latest",
            "--artifact-dir",
            str(custom_root),
            "--quiet-progress",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].artifact_dir == custom_root
    assert captured_configs[0].initial_review_file == custom_review
    assert captured_configs[0].initial_review_file != default_review


def test_main_save_profile_writes_project_config_and_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text("[defaults.pipeline]\nfinal_review = false\n", encoding="utf-8")

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--base",
            "trunk",
            "--max-iterations",
            "7",
            "--final-review",
            "--review-model",
            "gpt-5.5",
            "--remediation-model",
            "gpt-5.4-mini",
            "--reasoning-effort",
            "medium",
            "--timeout-seconds",
            "1800",
            "--summary-format",
            "text",
            "--debug-status-detection",
            "--terminal-title",
            "--check",
            "pytest -q",
            "--check",
            "git diff --check",
            "--progress-style",
            "rich",
            "--commit-after-remediation",
            "--commit-message-model",
            "gpt-5.3-codex-spark",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    project_config = profiles.project_config_path(tmp_path)
    saved = project_config.read_text(encoding="utf-8")
    assert "[profiles.final-pr]" in saved
    assert "base = \"trunk\"" in saved
    assert "max_iterations = 7" in saved
    assert "\"pytest -q\"" in saved
    assert "\"git diff --check\"" in saved
    assert "model = \"gpt-5.5\"" in saved
    assert "final_review = true" in saved
    assert "progress_style = \"rich\"" in saved
    assert "terminal_title = true" in saved
    assert "enabled = true" in saved


def test_main_save_profile_preserves_disabled_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--timeout-seconds",
            "0",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    saved = profiles.project_config_path(tmp_path).read_text(encoding="utf-8")
    assert saved.count("timeout_seconds = 0") == 2


def test_main_save_profile_is_non_destructive_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text("[profiles.final-pr]\ndescription = \"Keep me\"\n", encoding="utf-8")

    exit_code = cli_main.main(["--save-profile", "final-pr"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "profile already exists: final-pr" in captured.err
    assert "Keep me" in project_config.read_text(encoding="utf-8")


def test_main_resolves_latest_initial_review_from_profile_artifact_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    custom_root = tmp_path / "custom-artifacts"
    custom_run = custom_root / "20260428T010000Z"
    sibling_root = tmp_path / "other-artifacts"
    sibling_run = sibling_root / "20260428T020000Z"
    custom_run.mkdir(parents=True)
    sibling_run.mkdir(parents=True)

    custom_review = custom_run / "review-final.txt"
    sibling_review = sibling_run / "review-final.txt"
    custom_review.write_text("custom", encoding="utf-8")
    sibling_review.write_text("sibling", encoding="utf-8")
    os.utime(custom_review, (1_000_000, 1_000_000))
    os.utime(sibling_review, (2_000_000, 2_000_000))

    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"""
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.output]
artifact_dir = "{custom_root}"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--initial-review-file",
            "latest",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].artifact_dir == custom_root
    assert captured_configs[0].initial_review_file == custom_review
    assert captured_configs[0].initial_review_file != sibling_review


def test_main_uses_profile_defaults_and_cli_overrides(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.pipeline]
base = "trunk"
max_iterations = 3
checks = ["pytest -q", "git diff --check"]

[profiles.final-pr.review]
model = "gpt-5.5"
reasoning_effort = "medium"
timeout_seconds = 1800

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"
reasoning_effort = "low"

[profiles.final-pr.commit]
enabled = true

[profiles.final-pr.output]
summary_format = "json"
debug_status_detection = true
quiet_progress = true

[profiles.final-pr.budgets]
max_wall_seconds = 120
max_tokens = 1000
max_usd = "0.75"
soft_warn_fraction = 0.5
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--profile", "final-pr", "--base", "main", "--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.base == "main"
    assert config.max_iterations == 3
    assert config.review_model == "gpt-5.5"
    assert config.remediation_model == "gpt-5.4-mini"
    assert config.reasoning_effort is None
    assert config.review_reasoning_effort == "medium"
    assert config.remediation_reasoning_effort == "low"
    assert config.commit_after_remediation is True
    assert config.commit_message_model == "gpt-5.3-codex-spark"
    assert config.timeout_seconds == 300
    assert config.check_commands == ("pytest -q", "git diff --check")
    assert config.debug_status_detection is True
    assert config.progress is False
    assert config.budget_config.max_wall_seconds == 120
    assert config.budget_config.max_tokens == 1000
    assert str(config.budget_config.max_usd) == "0.75"
    assert config.budget_config.soft_warn_fraction == 0.5


def test_default_artifact_dir_uses_revrem_namespace():
    artifact_dir = runner_mod.default_artifact_dir()

    assert artifact_dir.parts[:2] == (".revrem", "runs")
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{32}", artifact_dir.name)


def test_profile_timeout_rejects_negative_values():
    with pytest.raises(ValueError, match="profile phase timeout must be non-negative"):
        runner_mod.resolve_profile_timeout_seconds(-1)


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
    (linked_worktree / ".git").write_text(f"gitdir: {linked_git_dir}\n", encoding="utf-8")

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


def test_main_cli_boolean_negations_override_profile_enabled_values(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.runtime]
exec_json = true

[profiles.final-pr.output]
debug_status_detection = true
quiet_progress = true
terminal_title = true
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--dry-run",
            "--no-exec-json",
            "--no-debug-status-detection",
            "--no-quiet-progress",
            "--no-terminal-title",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.exec_json is False
    assert config.debug_status_detection is False
    assert config.progress is True
    assert config.terminal_title is False


def test_main_uses_profile_commit_message_harness(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            commit=profiles.CommitConfig(
                enabled=True,
                harness="claude",
                message_model="fast-commit",
            ),
        ),
    )
    args = cli_args.parse_args(["--profile", "final-pr", "--dry-run"])

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_message_harness == "claude"
    assert config.commit_message_model == "fast-commit"





def test_run_loop_skips_commit_cleanliness_check_during_dry_run(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        return runner_mod.CommandResult(list(args), 0, stdout="should not be used\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        dry_run=True,
        final_review=False,
        check_commands=("pytest -q",),
    )

    summary = runner_mod.run_loop(config, runner)

    assert calls == []
    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"


def test_main_can_reenable_profile_disabled_true_by_default_booleans(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.pipeline]
final_review = false

[profiles.final-pr.runtime]
full_auto = false
output_last_message = false
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--full-auto",
            "--output-last-message",
            "--final-review",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.full_auto is True
    assert config.output_last_message is True
    assert config.final_review is True


def test_main_can_disable_profile_commit_with_negative_flag(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.commit]
enabled = true
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        ["--profile", "final-pr", "--no-commit-after-remediation", "--dry-run"]
    )

    assert exit_code == 0
    assert captured_configs[0].commit_after_remediation is False


def test_main_commit_message_model_override_wins_over_profile_default(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.review]
model = "gpt-5.5"

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.commit]
enabled = true
message_model = "gpt-5.3-codex-spark"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--commit-message-model",
            "gpt-test-commit",
            "--commit-message-prompt",
            "Write a custom subject.",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].commit_after_remediation is True
    assert captured_configs[0].commit_message_model == "gpt-test-commit"
    assert captured_configs[0].commit_message_prompt == "Write a custom subject."
    assert captured_configs[0].commit_message_prompt_overridden is True


def test_main_commit_message_prompt_override_applies_when_profile_sets_prompt(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.commit]
message_prompt = "Write a custom subject."
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--profile", "final-pr", "--commit-message-model", "gpt-test-commit", "--dry-run"])

    assert exit_code == 0
    assert captured_configs[0].commit_message_prompt == "Write a custom subject."
    assert captured_configs[0].commit_message_prompt_overridden is True


def test_main_reasoning_effort_override_applies_to_review_and_remediation_only(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
reasoning_effort = "medium"

[profiles.final-pr.remediation]
reasoning_effort = "low"

[profiles.final-pr.triage]
enabled = true
model = "gpt-4.1"
reasoning_effort = "minimal"
timeout_seconds = 30
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        ["--profile", "final-pr", "--reasoning-effort", "high", "--dry-run"]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.reasoning_effort == "high"
    assert config.review_reasoning_effort == "high"
    assert config.remediation_reasoning_effort == "high"
    assert config.triage_enabled is True
    assert config.triage_model == "gpt-4.1"
    assert config.triage_reasoning_effort == "minimal"


def test_main_phase_reasoning_effort_overrides_win_independently(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.triage]
enabled = true
reasoning_effort = "minimal"

[profiles.final-pr.remediation]
reasoning_effort = "low"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--reasoning-effort",
            "medium",
            "--review-reasoning-effort",
            "high",
            "--triage-reasoning-effort",
            "low",
            "--remediation-reasoning-effort",
            "minimal",
            "--commit-reasoning-effort",
            "high",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.review_reasoning_effort == "high"
    assert config.triage_reasoning_effort == "low"
    assert config.remediation_reasoning_effort == "minimal"
    assert config.commit_reasoning_effort == "high"


def test_main_records_non_dry_run_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return {
            "run_id": "run-1",
            "started_at": "2026-05-02T10:00:00Z",
            "base": config.base,
            "profile": config.profile_name,
            "artifact_dir": str(config.artifact_dir),
            "max_iterations": config.max_iterations,
            "iterations": [{"iteration": 1, "review_status": "clear"}],
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "pending_check_failures": False,
            "artifact_paths": {"summary": str(config.artifact_dir / "summary.json")},
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)
    monkeypatch.setattr(runner_mod, "write_summary", lambda config, summary: None)

    assert cli_main.main(["--base", "main"]) == 0
    output = capsys.readouterr().out
    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"

    assert history_path.is_file()
    assert f"Run history: {history_path}" in output
    assert '"run_id": "run-1"' in history_path.read_text(encoding="utf-8")


def test_main_records_failed_runs_in_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    summary = {
        "run_id": "run-1",
        "started_at": "2026-05-02T10:00:00Z",
        "base": "main",
        "profile": "final-pr",
        "artifact_dir": str(tmp_path / "artifacts"),
        "max_iterations": 1,
        "iterations": [{"iteration": 1, "review_status": "findings", "triage_failed": True}],
        "final_status": "error",
        "stopped_reason": "triage_failed",
        "pending_check_failures": False,
        "error": "codex exec triage failed for iteration 1",
    }

    def fake_run_loop(config):
        raise runner_mod.RunLoopFailed(summary, "codex exec triage failed for iteration 1")

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main(["--base", "main", "--artifact-dir", str(tmp_path / "artifacts")]) == 1
    capsys.readouterr()

    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"

    assert history_path.is_file()
    history_text = history_path.read_text(encoding="utf-8")
    summary_text = (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    assert '"run_id": "run-1"' in history_text
    assert '"final_status": "error"' in history_text
    assert '"stopped_reason": "triage_failed"' in history_text
    assert '"history_path": "' in summary_text


def test_main_skips_history_for_dry_run_and_explicit_opt_out(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return {
            "run_id": "run-1",
            "started_at": "2026-05-02T10:00:00Z",
            "base": config.base,
            "artifact_dir": str(config.artifact_dir),
            "max_iterations": config.max_iterations,
            "iterations": [],
            "final_status": "clear",
            "stopped_reason": "review_clear",
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main(["--dry-run"]) == 0
    assert cli_main.main(["--no-run-history"]) == 0
    assert not (home / ".local" / "share" / "revrem" / "runs.jsonl").exists()


def test_main_skips_history_when_summary_has_no_run_id(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return {
            "artifact_dir": str(config.artifact_dir),
            "iterations": [],
            "final_status": "clear",
            "stopped_reason": "review_clear",
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main([]) == 0
    assert not (home / ".local" / "share" / "revrem" / "runs.jsonl").exists()


def test_history_list_command_outputs_recent_runs(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        '{"run_id":"old","final_status":"findings","stopped_reason":"max_iterations_reached","base":"main","artifact_dir":"tmp/old"}\n'
        '{"run_id":\n'
        '{"run_id":"new","final_status":"clear","stopped_reason":"review_clear","base":"main","artifact_dir":"tmp/new"}\n',
        encoding="utf-8",
    )

    assert cli_main.main(["history", "list", "--limit", "1"]) == 0
    text = capsys.readouterr().out
    assert "new clear (review_clear) base=main artifacts=tmp/new" in text
    assert "old" not in text

    assert cli_main.main(["history", "--format", "json", "list", "--limit", "1"]) == 0
    json_text = capsys.readouterr().out
    assert '"run_id": "new"' in json_text
    assert '"run_id": "old"' not in json_text


def test_main_model_override_applies_to_review_and_remediation_only(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
model = "gpt-5.5"

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.triage]
enabled = true
model = "gpt-triage"
reasoning_effort = "minimal"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--profile", "final-pr", "--model", "gpt-test", "--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.model == "gpt-test"
    assert config.review_model == "gpt-test"
    assert config.remediation_model == "gpt-test"
    assert config.triage_enabled is True
    assert config.triage_model == "gpt-triage"
    assert config.triage_reasoning_effort == "minimal"


def test_main_uses_shared_defaults_without_an_explicit_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.pipeline]
base = "trunk"
max_iterations = 4
checks = ["pytest -q"]

[defaults.review]
model = "gpt-5.5"
timeout_seconds = 300

[defaults.remediation]
model = "gpt-5.4-mini"
timeout_seconds = 1800

[defaults.output]
summary_format = "both"
quiet_progress = true
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.base == "trunk"
    assert config.max_iterations == 4
    assert config.check_commands == ("pytest -q",)
    assert config.review_model == "gpt-5.5"
    assert config.remediation_model == "gpt-5.4-mini"
    assert config.review_timeout_seconds == 300
    assert config.remediation_timeout_seconds == 1800
    assert config.timeout_seconds == 300
    assert config.progress is False
    assert config.progress_style == "compact"


def test_main_preserves_zero_timeout_from_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
timeout_seconds = 0

[profiles.final-pr.remediation]
timeout_seconds = 1800
""",
        encoding="utf-8",
    )
    args = cli_args.parse_args(["--profile", "final-pr", "--base", "main"])
    config, summary_format = config_builder.build_loop_config(args, tmp_path)
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        return runner_mod.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    assert summary_format == "text"
    assert config.timeout_seconds == 300
    assert config.review_timeout_seconds == 0
    assert config.remediation_timeout_seconds == 1800

    object.__setattr__(config, "preflight_enabled", False)
    summary = runner_mod.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert len(calls) == 1
    assert calls[0][2] is None


def test_build_loop_config_rejects_negative_profile_timeout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
timeout_seconds = -1
""",
        encoding="utf-8",
    )

    args = cli_args.parse_args(["--profile", "final-pr", "--base", "main"])

    with pytest.raises(ValueError, match="review.timeout_seconds must be 0 or greater"):
        config_builder.build_loop_config(args, tmp_path)





def test_main_uses_default_timeout_for_unset_phase_specific_timeout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.remediation]
timeout_seconds = 1800
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--profile", "final-pr", "--base", "main", "--dry-run"])

    assert exit_code == 0
    assert captured_configs[0].timeout_seconds == 300
    assert captured_configs[0].review_timeout_seconds == 300
    assert captured_configs[0].remediation_timeout_seconds == 1800


def test_config_commands_create_show_list_and_delete_profile(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert cli_main.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0

    editor = tmp_path / "editor.sh"
    editor.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$1\" > \"$EDITOR_LOG\"\n"
        "python -c 'from pathlib import Path; import sys; "
        'path = Path(sys.argv[1]); text = path.read_text(encoding="utf-8"); '
        'path.write_text(text.replace("Smoke profile", "Edited profile"), encoding="utf-8")\' "$1"\n',
        encoding="utf-8",
    )
    editor.chmod(0o755)
    editor_log = tmp_path / "editor.log"
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.setenv("EDITOR_LOG", str(editor_log))

    assert cli_main.main(["config", "edit", "smoke"]) == 0
    assert f"edited smoke in {home / '.config' / 'revrem' / 'profiles.toml'}" in capsys.readouterr().out
    assert editor_log.read_text(encoding="utf-8").strip() == str(home / ".config" / "revrem" / "profiles.toml")
    assert "Edited profile" in (home / ".config" / "revrem" / "profiles.toml").read_text(encoding="utf-8")
    assert cli_main.main(["config", "show", "smoke", "--format", "json"]) == 0
    assert '"description": "Edited profile"' in capsys.readouterr().out

    assert cli_main.main(["config", "list"]) == 0
    assert "smoke - Edited profile" in capsys.readouterr().out
    assert cli_main.main(["config", "list", "--format", "json"]) == 0
    assert '"name": "smoke"' in capsys.readouterr().out

    assert cli_main.main(["config", "show", "smoke", "--format", "json"]) == 0
    assert '"name": "smoke"' in capsys.readouterr().out

    assert cli_main.main(["config", "clone", "smoke", "smoke-copy"]) == 0
    assert "cloned smoke to smoke-copy" in capsys.readouterr().out
    assert cli_main.main(["config", "show", "smoke-copy", "--format", "json"]) == 0
    assert '"description": "Edited profile"' in capsys.readouterr().out

    assert cli_main.main(["config", "doctor", "--profile", "smoke", "--format", "json"]) == 0
    assert '"resolved_profile"' in capsys.readouterr().out

    assert cli_main.main(["config", "delete", "smoke", "--yes"]) == 0
    assert cli_main.main(["config", "show", "smoke"]) == 1


def test_config_new_prompts_for_common_fields_when_interactive(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    answers = iter(
        [
            "Interactive profile",
            "codex",
            "gpt-5.5",
            "gpt-5.4-mini",
            "high",
            "1800",
            "git diff --check",
        ]
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli_main.main(["config", "new", "interactive", "--interactive"]) == 0

    assert "created interactive" in capsys.readouterr().out
    resolved = profiles.resolve_profile("interactive", cwd=tmp_path, home=home)
    assert resolved.description == "Interactive profile"
    assert resolved.review.harness == "codex"
    assert resolved.review.model == "gpt-5.5"
    assert resolved.review.reasoning_effort == "high"
    assert resolved.review.timeout_seconds == 1800
    assert resolved.remediation.model == "gpt-5.4-mini"
    assert resolved.pipeline.checks == ("git diff --check",)


def test_config_new_auto_prompts_when_default_invocation_is_tty(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(runner_mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(runner_mod.sys.stdout, "isatty", lambda: True)
    answers = iter(
        [
            "TTY profile",
            "codex",
            "gpt-5.5",
            "gpt-5.4-mini",
            "medium",
            "0",
            "pytest -q",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli_main.main(["config", "new", "tty-profile"]) == 0

    resolved = profiles.resolve_profile("tty-profile", cwd=tmp_path, home=home)
    assert resolved.description == "TTY profile"
    assert resolved.review.model == "gpt-5.5"
    assert resolved.remediation.model == "gpt-5.4-mini"
    assert resolved.review.timeout_seconds is None
    assert resolved.pipeline.checks == ("pytest -q",)


def test_config_new_auto_skips_prompt_when_default_invocation_is_not_tty(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(runner_mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(runner_mod.sys.stdout, "isatty", lambda: False)

    def fail_input(_prompt):
        raise AssertionError("non-TTY default config new must not prompt")

    monkeypatch.setattr("builtins.input", fail_input)

    assert cli_main.main(["config", "new", "non-tty-profile"]) == 0

    resolved = profiles.resolve_profile("non-tty-profile", cwd=tmp_path, home=home)
    assert resolved.description == ""
    assert resolved.review.model is None
    assert resolved.pipeline.checks == ()


def test_config_new_no_interactive_preserves_scriptable_minimal_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_input(_prompt):
        raise AssertionError("--no-interactive must not prompt")

    monkeypatch.setattr("builtins.input", fail_input)

    assert cli_main.main(["config", "new", "scripted", "--no-interactive"]) == 0

    resolved = profiles.resolve_profile("scripted", cwd=tmp_path, home=home)
    assert resolved.description == ""
    assert resolved.review.model is None
    assert resolved.pipeline.checks == ()


def test_config_import_rejects_missing_source_file(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    missing = tmp_path / "missing.toml"

    assert cli_main.main(["config", "import", str(missing)]) == 1
    assert "profile import file not found" in capsys.readouterr().err
    assert not (home / ".config" / "revrem" / "profiles.toml").exists()


def test_config_list_includes_last_used_from_run_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert cli_main.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0

    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"profile": "smoke", "finished_at": "2026-05-01T08:00:00Z"}),
                json.dumps({"profile": "other", "finished_at": "2026-05-01T09:00:00Z"}),
                json.dumps({"profile": "smoke", "finished_at": "2026-05-02T10:00:00Z"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert cli_main.main(["config", "list"]) == 0
    output = capsys.readouterr().out
    assert "smoke - Smoke profile" in output
    assert str(home / ".config" / "revrem" / "profiles.toml") in output
    assert "last used 2026-05-02T10:00:00Z" in output

    assert cli_main.main(["config", "list", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == [
        {
            "description": "Smoke profile",
            "last_used_at": "2026-05-02T10:00:00Z",
            "name": "smoke",
            "source": str(home / ".config" / "revrem" / "profiles.toml"),
        }
    ]


def test_config_new_reports_profile_write_oserror(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_write_user_profile(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(runner_mod.profiles, "write_user_profile", fail_write_user_profile)

    assert cli_main.main(["config", "new", "smoke"]) == 1
    assert "ERROR: permission denied" in capsys.readouterr().err


def test_config_global_format_applies_before_subcommand_defaults(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert cli_main.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0
    assert cli_main.main(["config", "--format", "json", "doctor", "--profile", "smoke"]) == 0

    output = capsys.readouterr().out
    assert '"resolved_profile"' in output
    assert '"user_config"' in output


def test_config_edit_requires_editor(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    assert cli_main.main(["config", "new", "smoke"]) == 0

    monkeypatch.delenv("EDITOR", raising=False)

    assert cli_main.main(["config", "edit", "smoke"]) == 1
    assert "EDITOR is not set" in capsys.readouterr().err


def test_editor_command_preserves_unquoted_windows_path(monkeypatch):
    monkeypatch.setenv("EDITOR", r"C:\Tools\Code\code.exe")

    assert config_command._editor_command() == [r"C:\Tools\Code\code.exe"]
