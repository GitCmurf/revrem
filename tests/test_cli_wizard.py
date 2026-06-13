from __future__ import annotations

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
