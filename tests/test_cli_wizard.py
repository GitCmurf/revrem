from __future__ import annotations

import sys
import types
from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest

from code_review_loop import application as application_mod
from code_review_loop.cli import wizard
from code_review_loop.core.outcome import OutcomeClear

cli_main = import_module("code_review_loop.cli.main")


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _KeyboardInterruptInput(StringIO):
    def readline(self, *args, **kwargs):
        raise KeyboardInterrupt


class _FakeText:
    def __init__(self):
        self.parts = []

    def append(self, value, style=None):
        self.parts.append((value, style))


class _FakeConsole:
    printed = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def print(self, value, *args, **kwargs):
        self.printed.append((value, kwargs))


def _install_fake_rich(monkeypatch):
    _FakeConsole.printed = []
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    text_module = types.ModuleType("rich.text")
    console_module.Console = _FakeConsole
    text_module.Text = _FakeText
    monkeypatch.setitem(sys.modules, "rich", rich_module)
    monkeypatch.setitem(sys.modules, "rich.console", console_module)
    monkeypatch.setitem(sys.modules, "rich.text", text_module)


@pytest.fixture(autouse=True)
def _codex_home(tmp_path, monkeypatch):
    home = tmp_path / "home-global"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-5.5"\nmodel_reasoning_effort = "low"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))


def _write_profile(path: Path) -> None:
    path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.pipeline]
base = "trunk"
max_iterations = 2
checks = ["pytest -q"]

[profiles.final-pr.triage]
enabled = true
contract = "v2"

[profiles.final-pr.triage.routing]
enabled = true
default_route = "midtier"

[profiles.final-pr.triage.routes.midtier]
harness = "codex"
model = "gpt-5.4-mini"
""",
        encoding="utf-8",
    )


def test_wizard_keeps_profile_command_minimal_for_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    stdin = StringIO(
        "\n"  # accept run shape
        "\n"  # dry-run action
        "\n"  # use command
    )

    result = wizard.run_wizard(cwd=tmp_path, stdin=stdin, stdout=StringIO(), stderr=StringIO())

    assert result is not None
    assert result.argv == ("--profile", "final-pr", "--dry-run")
    assert result.shell_command == "revrem --profile final-pr --dry-run"
    assert result.action == "dry-run"


def test_wizard_first_screen_distinguishes_defaults_and_previews_commands(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.pipeline]
base = "develop"

[profiles.default]
description = "Saved from CLI"

[profiles.default.review]
model = "gpt-5.5"
reasoning_effort = "low"
""",
        encoding="utf-8",
    )
    stderr = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("config\nq\n"), stderr=stderr)

    assert result is None
    rendered = stderr.getvalue()
    assert "no profile (merged defaults)" in rendered
    assert "default: (~/.config/revrem/profiles.toml)" in rendered
    assert "final-pr: (./.revrem.toml)" in rendered
    assert "command: revrem --profile default" in rendered
    assert "command: revrem --profile final-pr" in rendered
    assert "review=codex,gpt-5.5" not in rendered


def test_wizard_run_shape_previews_models_routes_checks_and_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    stderr = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=stderr)

    assert result is None
    rendered = stderr.getvalue()
    assert "Run shape: final-pr" in rendered
    assert "command: revrem --profile final-pr" in rendered
    assert "base: trunk" in rendered
    assert "remediation passes: max 2" in rendered
    assert "terminal output: text summary, compact progress" in rendered
    assert "+-- review: uses codex:gpt-5.5(low)" in rendered
    assert "+-- triage: uses codex:gpt-5.5(low)" in rendered
    assert "route midtier: uses codex:gpt-5.4-mini" in rendered
    assert "+-- remediation and verification" in rendered
    assert "remediate: uses codex:gpt-5.5(low)" in rendered
    assert "verify: 1 checks" in rendered
    assert "1. pytest -q" in rendered
    assert "if verify fails: no inner retry" in rendered
    assert "if verify passes: commit off" in rendered
    assert "after pass limit: final review enabled" in rendered
    assert "provider command: codex review" in rendered


def test_wizard_dogfood_preview_shows_inner_check_retry_and_commit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".revrem.toml").write_text(
        """
[profiles.dogfood]
description = "Dogfood"

[profiles.dogfood.pipeline]
max_iterations = 3
checks = ["pytest -q"]

[profiles.dogfood.remediation]
model = "gpt-5.4-mini"

[profiles.dogfood.commit]
enabled = true
message_model = "gpt-5.3-codex-spark"

[profiles.dogfood.runtime]
inner_check_retries = 1
""",
        encoding="utf-8",
    )
    stderr = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=stderr)

    assert result is None
    rendered = stderr.getvalue()
    assert "remediation passes: max 3" in rendered
    assert "if verify fails: retry remediation up to 1 time" in rendered
    assert "+-- if verify passes: commit enabled" in rendered
    assert "commit message: uses codex:gpt-5.3-codex-spark" in rendered
    assert "provider command: codex exec" in rendered


def test_wizard_builds_common_overrides_and_quotes_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    stdin = StringIO(
        "settings\n"
        "main\n"
        "3\n"
        "custom\n"
        "pytest -q tests/unit\n"
        "git diff --check\n"
        "\n"
        "n\n"
        "verbose\n"
        "both\n"
        "600\n"
        "models\n"
        "triage\n"
        "n\n"
        "remediation\n"
        "\n"
        "gpt-test\n"
        "high\n"
        "timeout\n"
        "0\n"
        "commit\n"
        "n\n"
        "pending\n"
        "ignore\n"
        "done\n"
        "\n"
        "print\n"
        "\n"
    )
    stdout = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=stdin, stdout=stdout, stderr=StringIO())

    assert result is not None
    assert result.argv == (
        "--profile",
        "final-pr",
        "--base",
        "main",
        "--max-iterations",
        "3",
        "--check",
        "pytest -q tests/unit",
        "--check",
        "git diff --check",
        "--skip-final-review",
        "--no-triage",
        "--remediation-model",
        "gpt-test",
        "--remediation-reasoning-effort",
        "high",
        "--timeout-seconds",
        "0",
        "--progress-style",
        "verbose",
        "--summary-format",
        "both",
        "--max-wall-seconds",
        "600",
        "--pending-review",
        "ignore",
    )
    assert "revrem --profile final-pr --base main --max-iterations 3" in result.shell_command
    assert "'pytest -q tests/unit'" in result.shell_command
    assert result.action == "print"


def test_wizard_sets_review_and_remediation_efforts_independently(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    stdin = StringIO(
        "models\n"
        "review\n"
        "\n"
        "gpt-review\n"
        "low\n"
        "remediation\n"
        "\n"
        "gpt-remediate\n"
        "high\n"
        "done\n"
        "\n"
        "print\n"
        "\n"
    )

    result = wizard.run_wizard(cwd=tmp_path, stdin=stdin, stdout=StringIO(), stderr=StringIO())

    assert result is not None
    assert result.argv == (
        "--profile",
        "final-pr",
        "--review-model",
        "gpt-review",
        "--review-reasoning-effort",
        "low",
        "--remediation-model",
        "gpt-remediate",
        "--remediation-reasoning-effort",
        "high",
    )
    assert "--reasoning-effort" not in result.argv
    assert "--model" not in result.argv


def test_wizard_sets_triage_and_commit_efforts_independently(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    stdin = StringIO(
        "models\n"
        "triage\n"
        "\n"
        "\n"
        "gpt-triage\n"
        "minimal\n"
        "\n"  # keep routing enabled
        "\n"  # keep default route
        "commit\n"
        "y\n"
        "\n"
        "gpt-commit\n"
        "low\n"
        "done\n"
        "\n"
        "print\n"
        "\n"
    )

    result = wizard.run_wizard(cwd=tmp_path, stdin=stdin, stdout=StringIO(), stderr=StringIO())

    assert result is not None
    assert "--triage-model" in result.argv
    assert "gpt-triage" in result.argv
    assert "--triage-reasoning-effort" in result.argv
    assert "--commit-message-model" in result.argv
    assert "gpt-commit" in result.argv
    assert "--commit-reasoning-effort" in result.argv


def test_wizard_no_profile_cannot_enable_routing_without_routes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    stderr = StringIO()
    stdin = StringIO(
        "config\n"
        "no-profile\n"
        "models\n"
        "triage\n"
        "y\n"
        "\n"  # harness
        "\n"  # model
        "\n"  # effort
        "routing\n"
        "done\n"
        "\n"  # accept
        "dry-run\n"
        "\n"
    )

    result = wizard.run_wizard(cwd=tmp_path, stdin=stdin, stdout=StringIO(), stderr=stderr)

    assert result is not None
    assert "--routing" not in result.argv
    assert "--route" not in result.argv
    assert "No profile routes are defined, so routing stays off." in stderr.getvalue()


def test_wizard_detects_repo_check_presets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "dev-check").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\n[tool.mypy]\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("<!-- MEMINIT_PROTOCOL: begin -->", encoding="utf-8")
    stdin = StringIO(
        "settings\n"
        "\n"
        "\n"
        "repo-gate\n"
        "\n"
            "\n"
            "\n"
            "\n"
            "accept\n"
            "print\n"
            "\n"
        )
    stderr = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=stdin, stdout=StringIO(), stderr=stderr)

    assert result is not None
    assert result.argv == ("--check", "./scripts/dev-check")
    rendered = stderr.getvalue()
    assert "repo gate: ./scripts/dev-check" in rendered
    assert "Python fast: pytest -q" in rendered
    assert "Python static: ruff check . && mypy src" in rendered
    assert "Meminit DocOps: uv run --locked meminit check --format json" in rendered


def test_wizard_blocks_provider_actions_when_model_is_unresolved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".revrem.toml").write_text(
        """
[profiles.claude-review]
description = "Claude review without explicit model"

[profiles.claude-review.review]
harness = "claude"
""",
        encoding="utf-8",
    )
    stderr = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("\nq\n"), stderr=stderr)

    assert result is None
    rendered = stderr.getvalue()
    assert "review: uses claude:model unresolved" in rendered
    assert "status: model unresolved - edit models before running" in rendered
    action_section = rendered.split("What should the wizard do?", maxsplit=1)[1]
    assert "print: print the command only" in action_section
    assert "dry-run" not in action_section
    assert "run: start the real run" not in action_section
    assert "save-profile" not in action_section


def test_wizard_cancel_returns_none(tmp_path):
    (tmp_path / ".git").mkdir()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=StringIO())

    assert result is None


def test_wizard_keyboard_interrupt_returns_cancelled(tmp_path):
    (tmp_path / ".git").mkdir()
    stderr = StringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=_KeyboardInterruptInput(), stderr=stderr)

    assert result is None
    assert "Cancelled before provider calls." in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_wizard_uses_rich_when_available_and_terminal_supports_it(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    _install_fake_rich(monkeypatch)
    monkeypatch.delenv("NO_COLOR", raising=False)
    stderr = _TtyStringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=stderr)

    assert result is None
    printed_values = [value for value, _kwargs in _FakeConsole.printed]
    assert any(isinstance(value, _FakeText) for value in printed_values)
    assert "Run shape: final-pr (./.revrem.toml)" in printed_values


def test_wizard_skips_rich_when_no_color_is_set(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    _install_fake_rich(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    stderr = _TtyStringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=stderr)

    assert result is None
    assert _FakeConsole.printed == []
    assert "Run shape: final-pr" in stderr.getvalue()


def test_main_explicit_wizard_uses_generated_argv(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    captured = {}

    def fake_wizard(*, cwd):
        captured["cwd"] = cwd
        return wizard.WizardResult(
            argv=("--dry-run", "--summary-format", "json"),
            shell_command="revrem --dry-run --summary-format json",
            action="dry-run",
        )

    def fake_run_loop(config):
        captured["config"] = config
        return application_mod.ReviewLoopResult(
            summary={
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "dry_run",
                "iterations": [],
            },
            outcome=OutcomeClear(reason="dry_run"),
        )

    monkeypatch.setattr(cli_main, "run_wizard", fake_wizard)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main(["--wizard"]) == 0

    assert captured["cwd"] == tmp_path
    assert captured["config"].dry_run is True
    assert '"final_status": "clear"' in capsys.readouterr().out


def test_main_wizard_with_other_options_still_launches_wizard(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    captured = {}

    def fake_wizard(*, cwd):
        captured["cwd"] = cwd
        return wizard.WizardResult(
            argv=(),
            shell_command="revrem",
            action="print",
        )

    def fail_parse_args(argv):
        raise AssertionError(f"parse_args should not run for wizard input: {list(argv)}")

    monkeypatch.setattr(cli_main, "run_wizard", fake_wizard)
    monkeypatch.setattr(cli_main, "parse_args", fail_parse_args)

    assert cli_main.main(["--wizard", "--profile", "final-pr"]) == 0

    assert captured["cwd"] == tmp_path
    assert capsys.readouterr().out == ""


def test_main_bare_revrem_uses_wizard_only_for_tty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    captured = {}

    def fake_wizard(*, cwd):
        captured["wizard"] = cwd
        return wizard.WizardResult(argv=(), shell_command="revrem", action="print")

    def fake_parse_args(argv):
        captured["argv"] = list(argv)
        raise SystemExit(77)

    monkeypatch.setattr(cli_main, "run_wizard", fake_wizard)
    monkeypatch.setattr(cli_main, "parse_args", fake_parse_args)
    monkeypatch.setattr("sys.stdin", _TtyStringIO(""))
    monkeypatch.setattr("sys.stdout", _TtyStringIO())

    assert cli_main.main([]) == 0
    assert captured["wizard"] == tmp_path
    assert "argv" not in captured

    captured.clear()
    monkeypatch.setattr("sys.stdin", StringIO(""))
    monkeypatch.setattr("sys.stdout", StringIO())
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main([])
    assert excinfo.value.code == 77
    assert captured["argv"] == []


def test_main_explicit_wizard_keyboard_interrupt_exits_130(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_wizard(*, cwd):
        return None

    monkeypatch.setattr(cli_main, "run_wizard", fake_wizard)

    assert cli_main.main(["--wizard"]) == 130
