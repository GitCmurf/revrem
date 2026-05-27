from __future__ import annotations

import os
from importlib import import_module

from code_review_loop import application as application_mod
from code_review_loop import profiles
from code_review_loop.core.outcome import OutcomeClear

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")


def _clear_result(summary: dict[str, object]) -> application_mod.ReviewLoopResult:
    return application_mod.ReviewLoopResult(summary=summary, outcome=OutcomeClear(reason="review_clear"))



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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
message_model = "gpt-5.3-codex-spark"

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
