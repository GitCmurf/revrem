from __future__ import annotations

from importlib import import_module

import tests.support.application_runner as runner_mod
from code_review_loop import application as application_mod
from code_review_loop import profiles
from code_review_loop.cli import args as cli_args
from code_review_loop.cli import config_builder
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import OutcomeClear
from code_review_loop.core.ports import CommandResult

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")


def _clear_result(summary: dict[str, object]) -> application_mod.ReviewLoopResult:
    return application_mod.ReviewLoopResult(summary=summary, outcome=OutcomeClear(reason="review_clear"))


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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
                reasoning_effort="low",
                timeout_seconds=0,
            ),
        ),
    )
    args = cli_args.parse_args(["--profile", "final-pr", "--dry-run"])

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_message_harness == "claude"
    assert config.commit_message_model == "fast-commit"
    assert config.commit_reasoning_effort == "low"
    assert config.commit_timeout_seconds == 0


def test_cli_commit_reasoning_effort_overrides_profile_commit_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            commit=profiles.CommitConfig(
                enabled=True,
                reasoning_effort="low",
                timeout_seconds=0,
            ),
        ),
    )
    args = cli_args.parse_args([
        "--profile",
        "final-pr",
        "--dry-run",
        "--commit-reasoning-effort",
        "high",
    ])

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_reasoning_effort == "high"
    assert config.commit_timeout_seconds == 0





def test_run_loop_skips_commit_cleanliness_check_during_dry_run(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        return CommandResult(list(args), 0, stdout="should not be used\n")

    config = LoopConfig(
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

    summary = runner_mod.run_loop(config, runner).to_dict()

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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        })

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
