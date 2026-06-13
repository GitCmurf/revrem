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
        "\n"  # selected profile
        "\n"  # base
        "\n"  # max iterations
        "\n"  # checks
        "\n"  # final review
        "\n"  # no advanced
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

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=stderr)

    assert result is None
    rendered = stderr.getvalue()
    assert "Default command: revrem --profile default" in rendered
    assert "no profile (merged defaults)" in rendered
    assert "default: (~/.config/revrem/profiles.toml)" in rendered
    assert "final-pr: (./.revrem.toml)" in rendered
    assert "command: revrem --profile default" in rendered
    assert "command: revrem --profile final-pr" in rendered
    assert "base=develop" in rendered
    assert "review=codex,gpt-5.5,effort=low" in rendered
    assert "triage=v2,codex,routing=midtier" in rendered
    assert "remediate=codex" in rendered
    assert "commit=off" in rendered


def test_wizard_builds_common_overrides_and_quotes_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    stdin = StringIO(
        "final-pr\n"
        "main\n"
        "3\n"
        "replace\n"
        "pytest -q tests/unit\n"
        "git diff --check\n"
        "\n"
        "n\n"
        "y\n"
        "n\n"
        "gpt-test\n"
        "high\n"
        "0\n"
        "n\n"
        "verbose\n"
        "both\n"
        "600\n"
        "ignore\n"
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
        "--model",
        "gpt-test",
        "--reasoning-effort",
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
    flattened_parts = [
        part
        for value in printed_values
        if isinstance(value, _FakeText)
        for part in value.parts
    ]
    assert ("Default command: ", "bold") in flattened_parts
    assert ("revrem --profile final-pr", "green") in flattened_parts
    assert any(part == (" [default]", "yellow") for part in flattened_parts)


def test_wizard_skips_rich_when_no_color_is_set(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    _write_profile(tmp_path / ".revrem.toml")
    _install_fake_rich(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    stderr = _TtyStringIO()

    result = wizard.run_wizard(cwd=tmp_path, stdin=StringIO("q\n"), stderr=stderr)

    assert result is None
    assert _FakeConsole.printed == []
    assert "Default command: revrem --profile final-pr" in stderr.getvalue()


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
