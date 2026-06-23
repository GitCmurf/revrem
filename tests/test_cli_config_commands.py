from __future__ import annotations

import json
import sys
from importlib import import_module
from types import SimpleNamespace

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import application as application_mod
from code_review_loop import profiles
from code_review_loop.cli import args as cli_args
from code_review_loop.cli import config_builder
from code_review_loop.core.outcome import OutcomeClear
from code_review_loop.core.ports import CommandResult

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")


def _clear_result(summary: dict[str, object]) -> application_mod.ReviewLoopResult:
    return application_mod.ReviewLoopResult(
        summary=summary, outcome=OutcomeClear(reason="review_clear")
    )


def test_config_unknown_command_reports_command_error(monkeypatch, capsys):
    monkeypatch.setattr(
        config_command,
        "parse_config_args",
        lambda _argv: SimpleNamespace(command="wat"),
    )

    assert config_command.main([]) == 1
    assert "unhandled config command: wat" in capsys.readouterr().err


def test_suppress_unknown_command_reports_command_error(monkeypatch, capsys):
    monkeypatch.setattr(
        suppress_command,
        "parse_suppress_args",
        lambda _argv: SimpleNamespace(command="wat", scope="repo"),
    )

    assert suppress_command.main([]) == 1
    assert "unhandled suppress command: wat" in capsys.readouterr().err


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

    exit_code = cli_main.main(["--profile", "final-pr", "--model", "gpt-test", "--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.model == "gpt-test"
    assert config.review_model == "gpt-test"
    assert config.remediation_model == "gpt-test"
    assert config.triage_enabled is True
    assert config.triage_model == "gpt-triage"
    assert config.triage_reasoning_effort == "low"


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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

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
        return CommandResult(
            list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n"
        )

    assert summary_format == "text"
    assert config.timeout_seconds == 300
    assert config.review_timeout_seconds == 0
    assert config.remediation_timeout_seconds == 1800

    object.__setattr__(config, "preflight_enabled", False)
    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"
    assert len(calls) == 1
    assert calls[0][2] is None


def test_phase_timeout_flags_override_shared_timeout(tmp_path, monkeypatch):
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
timeout_seconds = 1800

[profiles.final-pr.remediation]
timeout_seconds = 1800

[profiles.final-pr.commit]
enabled = true
timeout_seconds = 300
""",
        encoding="utf-8",
    )
    args = cli_args.parse_args(
        [
            "--profile",
            "final-pr",
            "--timeout-seconds",
            "600",
            "--review-timeout-seconds",
            "0",
            "--remediation-timeout-seconds",
            "900",
            "--commit-timeout-seconds",
            "120",
            "--check-timeout-seconds",
            "30",
            "--dry-run",
        ]
    )
    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    assert config.timeout_seconds == 600
    assert config.review_timeout_seconds == 0
    assert config.review_timeout_seconds_display == 0
    assert config.remediation_timeout_seconds == 900
    assert config.commit_timeout_seconds == 120
    assert config.check_timeout_seconds == 30
    assert config.phase_config_field_sources["review"]["timeout_seconds"] == "cli"
    assert config.phase_config_field_sources["checks"]["timeout_seconds"] == "cli"


def test_main_preserves_zero_timeout_from_cli_for_review(tmp_path, monkeypatch):
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
timeout_seconds = 1800
""",
        encoding="utf-8",
    )
    captured_timeouts: list[float | None] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        captured_timeouts.append(timeout_seconds)
        return CommandResult(
            list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n"
        )

    args = cli_args.parse_args(
        ["--profile", "final-pr", "--review-timeout-seconds", "0", "--base", "main"]
    )
    config, summary_format = config_builder.build_loop_config(args, tmp_path)

    assert summary_format == "text"
    assert config.review_timeout_seconds == 0
    assert config.review_timeout_seconds_display == 0

    object.__setattr__(config, "preflight_enabled", False)
    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"
    assert captured_timeouts == [None]


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


def test_build_loop_config_rejects_negative_profile_check_timeout(tmp_path, monkeypatch):
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
check_timeout_seconds = -1
""",
        encoding="utf-8",
    )

    args = cli_args.parse_args(["--profile", "final-pr", "--base", "main"])

    with pytest.raises(ValueError, match="pipeline.check_timeout_seconds must be 0 or greater"):
        config_builder.build_loop_config(args, tmp_path)


def test_build_loop_config_rejects_non_positive_external_review_input_chars(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    args = cli_args.parse_args(["--base", "main", "--external-review-input-chars", "0"])

    with pytest.raises(ValueError, match="external_review_input_chars must be greater than 0"):
        config_builder.build_loop_config(args, tmp_path)


def test_gemini_pro_default_review_input_chars_exceeds_standard_default():
    from code_review_loop.config import (
        DEFAULT_EXTERNAL_REVIEW_INPUT_CHARS,
        DEFAULT_GEMINI_PRO_REVIEW_INPUT_CHARS,
    )
    from code_review_loop.harnesses import GEMINI_ARGV_PROMPT_MAX_BYTES

    assert DEFAULT_GEMINI_PRO_REVIEW_INPUT_CHARS > DEFAULT_EXTERNAL_REVIEW_INPUT_CHARS
    assert DEFAULT_GEMINI_PRO_REVIEW_INPUT_CHARS < GEMINI_ARGV_PROMPT_MAX_BYTES


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
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--profile", "final-pr", "--base", "main", "--dry-run"])

    assert exit_code == 0
    assert captured_configs[0].timeout_seconds == 300
    assert captured_configs[0].review_timeout_seconds == 300
    assert captured_configs[0].remediation_timeout_seconds == 1800


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX shell editor script")
def test_config_commands_create_show_list_and_delete_profile(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert cli_main.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0

    editor = tmp_path / "editor.sh"
    editor.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$1" > "$EDITOR_LOG"\n'
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
    assert (
        f"edited smoke in {home / '.config' / 'revrem' / 'profiles.toml'}"
        in capsys.readouterr().out
    )
    assert editor_log.read_text(encoding="utf-8").strip() == str(
        home / ".config" / "revrem" / "profiles.toml"
    )
    assert "Edited profile" in (home / ".config" / "revrem" / "profiles.toml").read_text(
        encoding="utf-8"
    )
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
    monkeypatch.setattr(config_command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(config_command.sys.stdout, "isatty", lambda: True)
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
    monkeypatch.setattr(config_command.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(config_command.sys.stdout, "isatty", lambda: False)

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
    assert {
        "description": "Smoke profile",
        "last_used_at": "2026-05-02T10:00:00Z",
        "name": "smoke",
        "source": str(home / ".config" / "revrem" / "profiles.toml"),
    } in data


def test_config_new_reports_profile_write_oserror(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_write_user_profile(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(profiles, "write_user_profile", fail_write_user_profile)

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


def test_editor_command_uses_windows_quoting_when_needed(monkeypatch):
    monkeypatch.setenv("EDITOR", '"C:\\Program Files\\Editor\\editor.exe" --wait')
    monkeypatch.setattr(config_command.os, "name", "nt")

    assert config_command._editor_command() == [
        "C:\\Program Files\\Editor\\editor.exe",
        "--wait",
    ]


def test_is_large_context_gemini_review_model_accepts_canonical_pro_names():
    assert config_builder.is_large_context_gemini_review_model("gemini", "gemini-3.1-pro-preview")
    assert config_builder.is_large_context_gemini_review_model("gemini", "gemini-3-pro")
    assert config_builder.is_large_context_gemini_review_model("gemini", "gemini-2.5-pro")


def test_is_large_context_gemini_review_model_rejects_pretend_pro_suffixes():
    assert not config_builder.is_large_context_gemini_review_model(
        "gemini", "gemini-2.5-pretend-pro"
    )
    assert not config_builder.is_large_context_gemini_review_model(
        "gemini", "gemini-2.5-prosomething-experimental"
    )
    assert not config_builder.is_large_context_gemini_review_model("gemini", "gemini-2.5-pro-")


def test_is_large_context_gemini_review_model_rejects_non_gemini_harness():
    assert not config_builder.is_large_context_gemini_review_model(
        "codex", "gemini-3.1-pro-preview"
    )
    assert not config_builder.is_large_context_gemini_review_model(
        "opencode", "gemini-3.1-pro-preview"
    )


def test_is_large_context_gemini_review_model_rejects_empty_model():
    assert not config_builder.is_large_context_gemini_review_model("gemini", None)
    assert not config_builder.is_large_context_gemini_review_model("gemini", "")


def test_is_large_context_gemini_review_model_accepts_multi_segment_pro_suffix():
    """Multi-segment Pro suffixes like ``-exp-03-25`` and ``-preview-09``
    are accepted and receive the large-context cap.
    """
    assert config_builder.is_large_context_gemini_review_model("gemini", "gemini-2.5-pro-exp-03-25")
    assert config_builder.is_large_context_gemini_review_model("gemini", "gemini-2.5-pro-exp-0827")
    assert config_builder.is_large_context_gemini_review_model(
        "gemini", "gemini-3.1-pro-preview-09"
    )
