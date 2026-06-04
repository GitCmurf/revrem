from __future__ import annotations

from importlib import import_module

import tests.support.application_runner as runner_mod
from code_review_loop import application as application_mod
from code_review_loop import profiles, reporting
from code_review_loop.cli import args as cli_args
from code_review_loop.cli import config_builder
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import OutcomeClear
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import format_terminal_summary

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")


def _clear_result(summary: dict[str, object]) -> application_mod.ReviewLoopResult:
    return application_mod.ReviewLoopResult(
        summary=summary, outcome=OutcomeClear(reason="review_clear")
    )


def test_main_cli_boolean_negations_override_profile_enabled_values(
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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

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


def test_phase_config_payload_marks_unsupported_provider_reasoning_effort():
    config = LoopConfig(
        review_harness="opencode",
        review_reasoning_effort="low",
        triage_harness="opencode",
        triage_reasoning_effort="low",
        remediation_harness="opencode",
        remediation_reasoning_effort="medium",
        commit_message_harness="opencode",
        commit_reasoning_effort="low",
    )

    phase_config = reporting.phase_config_payload(config)

    assert phase_config["review"]["reasoning_effort"] == "low"
    assert phase_config["review"]["reasoning_effort_supported"] is False
    assert phase_config["review"]["provider_reasoning_effort"] is None
    assert phase_config["remediation"]["reasoning_effort"] == "medium"
    assert phase_config["remediation"]["reasoning_effort_supported"] is False
    assert phase_config["remediation"]["provider_reasoning_effort"] is None
    assert phase_config["commit_message"]["reasoning_effort_supported"] is False
    assert phase_config["commit_message"]["provider_reasoning_effort"] is None


def test_phase_config_payload_records_codex_provider_reasoning_effort():
    config = LoopConfig(
        review_harness="codex",
        review_reasoning_effort="high",
        triage_harness="codex",
        triage_reasoning_effort="low",
        remediation_harness="codex",
        remediation_reasoning_effort="medium",
        commit_message_harness="codex",
        commit_reasoning_effort="minimal",
    )

    phase_config = reporting.phase_config_payload(config)

    assert phase_config["review"]["reasoning_effort_supported"] is True
    assert phase_config["review"]["provider_reasoning_effort"] == "high"
    assert phase_config["triage"]["reasoning_effort_supported"] is True
    assert phase_config["triage"]["provider_reasoning_effort"] == "low"
    assert phase_config["commit_message"]["reasoning_effort_supported"] is True
    assert phase_config["commit_message"]["provider_reasoning_effort"] == "minimal"


def test_cli_commit_message_harness_overrides_profile_commit_harness(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            commit=profiles.CommitConfig(
                enabled=True,
                harness="codex",
                message_model="fast-commit",
            ),
        ),
    )
    args = cli_args.parse_args(
        [
            "--profile",
            "final-pr",
            "--commit-message-harness",
            "claude",
            "--dry-run",
        ]
    )

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_message_harness == "claude"
    assert config.phase_config_sources["commit_message"] == "mixed"
    assert config.phase_config_field_sources["commit_message"]["harness"] == "cli"


def test_cli_commit_harness_alias_overrides_profile_commit_harness(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            commit=profiles.CommitConfig(enabled=True, harness="codex"),
        ),
    )
    args = cli_args.parse_args(
        [
            "--profile",
            "final-pr",
            "--commit-harness",
            "gemini",
            "--dry-run",
        ]
    )

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_message_harness == "gemini"
    assert config.phase_config_field_sources["commit_message"]["harness"] == "cli"


def test_cli_review_and_remediation_harnesses_override_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            review=profiles.PhaseConfig(harness="codex", model="review-profile"),
            remediation=profiles.PhaseConfig(
                harness="codex",
                model="remediation-profile",
            ),
        ),
    )
    args = cli_args.parse_args(
        [
            "--profile",
            "final-pr",
            "--review-harness",
            "gemini",
            "--remediation-harness",
            "opencode",
            "--dry-run",
        ]
    )

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.review_harness == "gemini"
    assert config.remediation_harness == "opencode"
    assert config.phase_config_field_sources["review"]["harness"] == "cli"
    assert config.phase_config_field_sources["remediation"]["harness"] == "cli"
    saved = config_builder.profile_from_loop_config(
        "saved",
        config,
        summary_format="json",
    )
    assert saved.review.harness == "gemini"
    assert saved.remediation.harness == "opencode"


def test_gemini_pro_review_uses_large_context_default_when_cap_omitted(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".revrem.toml").write_text(
        """
[profiles.gemini-review.review]
harness = "gemini"
model = "gemini-3.1-pro-preview"
""",
        encoding="utf-8",
    )

    args = cli_args.parse_args(["--profile", "gemini-review", "--dry-run"])
    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.external_review_input_chars == 600_000
    assert (
        config.phase_config_field_sources["runtime"]["external_review_input_chars"]
        == "model-default"
    )


def test_explicit_external_review_cap_overrides_gemini_model_default(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".revrem.toml").write_text(
        """
[profiles.gemini-review.review]
harness = "gemini"
model = "gemini-3.1-pro-preview"

[profiles.gemini-review.runtime]
external_review_input_chars = 80000
""",
        encoding="utf-8",
    )

    args = cli_args.parse_args(
        [
            "--profile",
            "gemini-review",
            "--external-review-input-chars",
            "1234",
            "--dry-run",
        ]
    )
    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.external_review_input_chars == 1234
    assert (
        config.phase_config_field_sources["runtime"]["external_review_input_chars"]
        == "cli"
    )

    args = cli_args.parse_args(["--profile", "gemini-review", "--dry-run"])
    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.external_review_input_chars == 80_000
    assert (
        config.phase_config_field_sources["runtime"]["external_review_input_chars"]
        == "profile:gemini-review"
    )


def test_cli_commit_reasoning_effort_overrides_profile_commit_effort(
    tmp_path, monkeypatch
):
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
    args = cli_args.parse_args(
        [
            "--profile",
            "final-pr",
            "--dry-run",
            "--commit-reasoning-effort",
            "high",
        ]
    )

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_reasoning_effort == "high"
    assert config.commit_timeout_seconds == 0


def test_codex_commit_reasoning_effort_promotes_minimal_to_low(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            commit=profiles.CommitConfig(
                enabled=True,
                harness="codex",
                message_model="gpt-5.3-codex-spark",
                reasoning_effort="medium",
            ),
        ),
    )
    args = cli_args.parse_args(
        [
            "--profile",
            "final-pr",
            "--dry-run",
            "--commit-reasoning-effort",
            "minimal",
        ]
    )

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_reasoning_effort == "low"
    assert config.commit_reasoning_effort_requested == "minimal"
    assert (
        config.commit_reasoning_effort_adjustment
        == "codex_minimal_unsupported_by_model"
    )
    assert (
        config.phase_config_field_sources["commit_message"]["reasoning_effort"] == "cli"
    )
    phase_config = reporting.phase_config_payload(config)
    assert phase_config["commit_message"]["reasoning_effort"] == "low"
    assert phase_config["commit_message"]["requested_reasoning_effort"] == "minimal"
    assert (
        phase_config["commit_message"]["reasoning_effort_adjustment"]
        == "codex_minimal_unsupported_by_model"
    )


def test_codex_commit_reasoning_effort_keeps_minimal_for_unknown_model(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        config_builder,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="future",
            commit=profiles.CommitConfig(
                enabled=True,
                harness="codex",
                message_model="gpt-future-codex",
            ),
        ),
    )
    args = cli_args.parse_args(
        [
            "--profile",
            "future",
            "--dry-run",
            "--commit-reasoning-effort",
            "minimal",
        ]
    )

    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.commit_reasoning_effort == "minimal"
    assert config.commit_reasoning_effort_requested == "minimal"
    assert config.commit_reasoning_effort_adjustment is None


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


def test_main_can_reenable_profile_disabled_true_by_default_booleans(
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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        ["--profile", "final-pr", "--no-commit-after-remediation", "--dry-run"]
    )

    assert exit_code == 0
    assert captured_configs[0].commit_after_remediation is False


def test_main_commit_message_model_override_wins_over_profile_default(
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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--commit-message-model",
            "gpt-test-commit",
            "--dry-run",
        ]
    )

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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

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


def test_main_triage_cli_overrides_profile_disabled_values(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.triage]
enabled = false
contract = "v1"
harness = "codex"
model = "profile-triage"

[profiles.final-pr.triage.routing]
enabled = false
default_route = "midtier-coder"
strict_on_unavailable_route = true

[profiles.final-pr.triage.routes.midtier-coder]
harness = "codex"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--triage",
            "--triage-contract",
            "v2",
            "--triage-model",
            "cli-triage",
            "--triage-harness",
            "gemini",
            "--triage-timeout-seconds",
            "0",
            "--routing",
            "--no-routing-strict",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.triage_enabled is True
    assert config.triage_contract == "v2"
    assert config.triage_model == "cli-triage"
    assert config.triage_harness == "gemini"
    assert config.triage_timeout_seconds is None
    assert config.triage_timeout_seconds_display == 0
    assert config.phase_config_sources["triage"] == "mixed"
    assert config.phase_config_field_sources["triage"] == {
        "enabled": "cli",
        "harness": "cli",
        "model": "cli",
        "reasoning_effort": "profile:final-pr",
        "timeout_seconds": "cli",
        "contract": "cli",
        "routing_enabled": "cli",
        "routing_strict": "cli",
        "routing_default_route": "profile:final-pr",
        "allow_model_escalation": "profile:final-pr",
    }
    assert config.profile_v2 is not None
    assert config.profile_v2.triage.routing.enabled is True
    assert config.profile_v2.triage.routing.strict_on_unavailable_route is False
    assert config.profile_v2.triage.routing.allow_model_escalation is True
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "artifact_paths": {"reviews": ["tmp/run/review-final.txt"]},
            "base": "main",
            "max_iterations": 1,
            "resume_config": {
                "base": "main",
                "max_iterations": 1,
                "routing_strict": False,
            },
            "phase_config": reporting.phase_config_payload(config),
        }
    )
    assert "--no-routing-strict" in text


def test_main_triage_cli_negations_override_profile_enabled_values(
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
[profiles.final-pr.triage]
enabled = true
contract = "v2"

[profiles.final-pr.triage.routing]
enabled = true
strict_on_unavailable_route = true

[profiles.final-pr.triage.routes.midtier-coder]
harness = "codex"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        ["--profile", "final-pr", "--no-triage", "--no-routing", "--dry-run"]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.triage_enabled is False
    assert config.profile_v2 is not None
    assert config.profile_v2.triage.routing.enabled is False


def test_main_routing_model_escalation_cli_override(tmp_path, monkeypatch):
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
contract = "v2"

[profiles.final-pr.triage.routing]
enabled = true
default_route = "midtier-coder"
allow_model_escalation = true

[profiles.final-pr.triage.routes.midtier-coder]
harness = "codex"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--no-allow-model-escalation",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.profile_v2 is not None
    assert config.profile_v2.triage.routing.allow_model_escalation is False
    assert (
        config.phase_config_field_sources["triage"]["allow_model_escalation"] == "cli"
    )


def test_main_route_cli_override_forces_existing_profile_route(tmp_path, monkeypatch):
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
contract = "v2"

[profiles.final-pr.triage.routing]
enabled = true
default_route = "midtier-coder"

[profiles.final-pr.triage.routes.midtier-coder]
harness = "codex"

[profiles.final-pr.triage.routes.gemini-pro]
harness = "gemini"
model = "gemini-2.5-pro"
reasoning_effort = "high"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--route",
            "gemini-pro",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.profile_v2 is not None
    assert config.profile_v2.triage.routing.default_route == "gemini-pro"
    assert config.phase_config_field_sources["triage"]["routing_default_route"] == "cli"
    saved = config_builder.profile_from_loop_config(
        "saved",
        config,
        summary_format="json",
    )
    assert saved.triage.routing.default_route == "gemini-pro"


def test_main_route_cli_override_rejects_unknown_route(tmp_path, monkeypatch):
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
contract = "v2"

[profiles.final-pr.triage.routes.midtier-coder]
harness = "codex"
""",
        encoding="utf-8",
    )

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--route",
            "gemini-pro",
            "--dry-run",
        ]
    )

    assert exit_code == 1


def test_routing_override_requires_v2_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    exit_code = cli_main.main(["--routing", "--dry-run"])

    assert exit_code == 1
