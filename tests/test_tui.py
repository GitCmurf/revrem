from __future__ import annotations

import importlib.util
import sys
import types

from code_review_loop import tui
from code_review_loop.cli.main import main as cli_main


def test_tui_dry_run_does_not_require_textual(capsys):
    assert cli_main(["ui", "--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "RevRem TUI entry point is available." in captured.out
    assert captured.err == ""


def test_tui_main_uses_process_argv_when_called_without_explicit_argv(monkeypatch, capsys):
    monkeypatch.setattr(tui.sys, "argv", ["revrem", "--dry-run"])

    def fail_find_spec(name: str, *args, **kwargs):
        raise AssertionError(f"unexpected dependency check for {name}")

    monkeypatch.setattr(tui.importlib.util, "find_spec", fail_find_spec)

    assert tui.main() == 0

    captured = capsys.readouterr()
    assert "RevRem TUI entry point is available." in captured.out
    assert captured.err == ""


def test_tui_reports_missing_optional_dependency(monkeypatch, capsys):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name == "textual":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(tui.importlib.util, "find_spec", fake_find_spec)

    assert cli_main(["ui"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "requires the optional Textual dependency" in captured.err
    assert "revrem[tui]" in captured.err


def test_tui_reports_unknown_initial_profile(monkeypatch, tmp_path, capsys):
    app_module = types.ModuleType("textual.app")
    widgets_module = types.ModuleType("textual.widgets")
    app_module.App = object
    widgets_module.Header = object
    widgets_module.Footer = object
    widgets_module.Static = object
    monkeypatch.setitem(sys.modules, "textual.app", app_module)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_module)
    monkeypatch.setattr(tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    assert cli_main(["ui", "--profile", "missing"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: profile not found: missing" in captured.err


def test_tui_launches_textual_app_with_home_snapshot(monkeypatch, tmp_path):
    rendered_widgets = []
    launched = []

    class FakeApp:
        def run(self):
            launched.append(type(self).__name__)
            rendered_widgets.extend(list(self.compose()))

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    app_module = types.ModuleType("textual.app")
    widgets_module = types.ModuleType("textual.widgets")
    app_module.App = FakeApp
    widgets_module.Header = FakeWidget
    widgets_module.Footer = FakeWidget
    widgets_module.Static = FakeWidget
    monkeypatch.setitem(sys.modules, "textual.app", app_module)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_module)
    monkeypatch.setattr(tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    assert cli_main(["ui"]) == 0

    assert launched == ["RevRemApp"]
    body = rendered_widgets[1]
    assert body.kwargs["id"] == "body"
    assert body.kwargs["markup"] is True
    assert f"Workspace: {tmp_path}" in body.args[0]
    assert "[b]Home[/b]" in body.args[0]
    assert "[b]Profiles[/b]" in body.args[0]
    assert "[b]Pipeline[/b]" in body.args[0]
    assert "[b]Run Monitor[/b]" in body.args[0]


def test_tui_dry_run_action_launches_selected_profile(monkeypatch, tmp_path):
    actions = []
    notifications = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.pipeline]
base = "main"
checks = ["git diff --check"]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    class FakeApp:
        def run(self):
            self.action_launch_dry_run()
            actions.append(type(self).__name__)

        def notify(self, message):
            notifications.append(message)

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    app_module = types.ModuleType("textual.app")
    widgets_module = types.ModuleType("textual.widgets")
    app_module.App = FakeApp
    widgets_module.Header = FakeWidget
    widgets_module.Footer = FakeWidget
    widgets_module.Static = FakeWidget
    monkeypatch.setitem(sys.modules, "textual.app", app_module)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_module)
    monkeypatch.setattr(tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd):
        actions.append((plan.argv, cwd))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)

    assert cli_main(["ui"]) == 0

    assert actions[0][0] == ("revrem", "--profile", "final-pr", "--dry-run")
    assert actions[0][1] == tmp_path
    assert actions[1] == "RevRemApp"
    assert notifications == ["Dry run completed: final-pr"]


def test_tui_edit_action_launches_profile_editor_with_suspended_app(monkeypatch, tmp_path):
    actions = []
    notifications = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[profiles.final-pr]\ndescription = \"Final PR\"\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    class FakeSuspend:
        def __enter__(self):
            actions.append("suspend-enter")

        def __exit__(self, exc_type, exc, tb):
            actions.append("suspend-exit")
            return False

    class FakeApp:
        def run(self):
            self.action_edit_profile()
            actions.append(type(self).__name__)

        def suspend(self):
            return FakeSuspend()

        def notify(self, message):
            notifications.append(message)

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    app_module = types.ModuleType("textual.app")
    widgets_module = types.ModuleType("textual.widgets")
    app_module.App = FakeApp
    widgets_module.Header = FakeWidget
    widgets_module.Footer = FakeWidget
    widgets_module.Static = FakeWidget
    monkeypatch.setitem(sys.modules, "textual.app", app_module)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_module)
    monkeypatch.setattr(tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        actions.append((plan.argv, cwd, capture_output))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)

    assert cli_main(["ui", "--profile", "final-pr"]) == 0

    assert actions[:3] == [
        "suspend-enter",
        (("revrem", "config", "edit", "final-pr"), tmp_path, False),
        "suspend-exit",
    ]
    assert actions[3] == "RevRemApp"
    assert notifications == ["Edited profile: final-pr"]


def test_tui_profile_lifecycle_actions_use_config_commands(monkeypatch, tmp_path):
    actions = []
    notifications = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[profiles.final-pr]\ndescription = \"Final PR\"\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    class FakeInput:
        def __init__(self, value):
            self.value = value

    class FakeApp:
        def run(self):
            self.action_clone_profile()
            self.action_delete_profile()
            actions.append(type(self).__name__)

        def query_one(self, selector):
            assert selector == "#profile-name"
            return FakeInput("copy")

        def notify(self, message):
            notifications.append(message)

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    app_module = types.ModuleType("textual.app")
    widgets_module = types.ModuleType("textual.widgets")
    app_module.App = FakeApp
    widgets_module.Header = FakeWidget
    widgets_module.Footer = FakeWidget
    widgets_module.Static = FakeWidget
    monkeypatch.setitem(sys.modules, "textual.app", app_module)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_module)
    monkeypatch.setattr(tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        actions.append((plan.argv, cwd, capture_output))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)

    assert cli_main(["ui", "--profile", "final-pr"]) == 0

    assert actions[:2] == [
        (("revrem", "config", "clone", "final-pr", "copy"), tmp_path, True),
        (("revrem", "config", "delete", "copy", "--yes"), tmp_path, True),
    ]
    assert actions[2] == "RevRemApp"
    assert notifications == [
        "Cloned profile: final-pr -> copy",
        "Deleted profile: copy",
    ]


def test_run_launch_plan_uses_current_dev_entrypoint(tmp_path, monkeypatch):
    launcher = tmp_path / ".venv" / "bin" / "revrem"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    plan = tui.tui_state.LaunchPlan(
        profile_name="final-pr",
        mode="dry-run",
        argv=("revrem", "--profile", "final-pr", "--dry-run"),
        shell_command="revrem --profile final-pr --dry-run",
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui.sys, "argv", [str(launcher), "ui"])
    monkeypatch.setattr(tui.subprocess, "run", fake_run)

    result = tui.run_launch_plan(plan, cwd=tmp_path)

    assert result.returncode == 0
    assert calls[0][0] == [str(launcher), "--profile", "final-pr", "--dry-run"]
    assert calls[0][1]["cwd"] == tmp_path


def test_run_launch_plan_uses_module_entrypoint_when_console_script_is_missing(tmp_path, monkeypatch):
    package_main = tmp_path / "src" / "code_review_loop" / "__main__.py"
    package_main.parent.mkdir(parents=True)
    package_main.write_text("# module entrypoint\n", encoding="utf-8")
    plan = tui.tui_state.LaunchPlan(
        profile_name="final-pr",
        mode="dry-run",
        argv=("revrem", "--profile", "final-pr", "--dry-run"),
        shell_command="revrem --profile final-pr --dry-run",
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui.sys, "argv", [str(package_main), "ui"])
    monkeypatch.setattr(tui.subprocess, "run", fake_run)

    result = tui.run_launch_plan(plan, cwd=tmp_path)

    assert result.returncode == 0
    assert calls[0][0] == [
        tui.sys.executable,
        "-m",
        "code_review_loop",
        "--profile",
        "final-pr",
        "--dry-run",
    ]
    assert calls[0][1]["cwd"] == tmp_path
