from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

from code_review_loop import tui
from code_review_loop.cli.main import main as cli_main

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_workspace_order_is_loop_first():
    assert tui._WORKSPACES == ("loop", "run", "profiles", "prompts")


def test_tui_bindings_keep_i_workspace_dispatched():
    bindings = tui._build_bindings(None)
    i_bindings = [
        binding
        for binding in bindings
        if getattr(binding, "key", binding[0] if isinstance(binding, tuple) else None) == "i"
    ]
    assert len(i_bindings) == 1
    action = i_bindings[0][1] if isinstance(i_bindings[0], tuple) else i_bindings[0].action
    assert action == "edit_max_iterations"


def test_tui_help_lists_loop_and_profile_i_dispatch():
    help_text = tui._help_markup(visible=True)
    assert "\\[i] iterations" in help_text
    assert "\\[i] import profiles" in help_text


def _patch_textual_app_class(monkeypatch, run):
    class FakeRevRemApp(tui.RevRemApp):
        def run(self):
            run(self)

    FakeRevRemApp.__name__ = "RevRemApp"
    monkeypatch.setattr(tui, "textual_app_class", lambda: FakeRevRemApp)
    return FakeRevRemApp


class _WidgetProbe:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str]] = []
        self.classes: list[tuple[str, str]] = []

    def query_one(self, selector: str):
        if selector not in {
            "#screen-run-monitor",
            "#screen-home",
            "#screen-controls",
            "#screen-help",
            "#status-bar",
            "#footer-bar",
        }:
            raise AssertionError(f"unexpected selector: {selector}")
        probe = self

        class Widget:
            def update(self, value):
                probe.updates.append((selector, value))

            def set_classes(self, value):
                probe.classes.append((selector, value))

        return Widget()


def test_tui_dry_run_does_not_require_textual(capsys):
    assert cli_main(["ui", "--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "RevRem TUI entry point is available." in captured.out
    assert captured.err == ""


def test_tui_dry_run_survives_discoverable_broken_textual(tmp_path):
    result = _run_cli_with_broken_textual(tmp_path, "ui", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "RevRem TUI entry point is available." in result.stdout
    assert result.stderr == ""


def test_tui_module_import_does_not_import_discoverable_broken_textual(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "textual_app_imported"
    result = _run_python_with_broken_textual(
        tmp_path,
        "import code_review_loop.tui; print('import-ok')",
        sentinel=sentinel,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "import-ok\n"
    assert not sentinel.exists()


def test_tui_launch_reports_discoverable_broken_textual(tmp_path: Path) -> None:
    result = _run_cli_with_broken_textual(tmp_path, "ui")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Textual was found but could not be imported" in result.stderr
    assert "broken textual app import" in result.stderr


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
    _patch_textual_app_class(monkeypatch, lambda self: None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    assert cli_main(["ui", "--profile", "missing"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: profile not found: missing" in captured.err


def test_tui_launches_textual_app_with_home_snapshot(monkeypatch, tmp_path):
    rendered = []
    launched = []

    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run(self):
        launched.append(type(self).__name__)
        rendered.append(tui.tui_state.render_shell_text(self.model))

    _patch_textual_app_class(monkeypatch, fake_run)

    assert cli_main(["ui"]) == 0

    assert launched == ["RevRemApp"]
    assert f"Workspace: {tmp_path}" in rendered[0]
    assert "[b]Home[/b]" in rendered[0]
    assert "[b]Profiles[/b]" in rendered[0]
    assert "[b]Pipeline[/b]" in rendered[0]
    assert "[b]Run Monitor[/b]" in rendered[0]


def test_phase_summary_line_escapes_enabled_marker_for_markup():
    phase = tui.tui_state.PhaseView(name="review", enabled=True)
    assert tui._phase_summary_line(phase, selected=False).startswith("[[ok]] review: ")


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

    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd):
        actions.append((plan.argv, cwd))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    app_class = _patch_textual_app_class(
        monkeypatch,
        lambda self: (self.action_launch_dry_run(), actions.append(type(self).__name__)),
    )
    monkeypatch.setattr(app_class, "notify", lambda self, message: notifications.append(message))

    assert cli_main(["ui"]) == 0

    assert actions[0][0] == ("revrem", "--profile", "final-pr", "--dry-run")
    assert actions[0][1] == tmp_path
    assert actions[1] == "RevRemApp"
    assert notifications == ["Dry run completed: final-pr"]


def test_tui_dry_run_action_launches_builtin_profile_without_local_config(
    monkeypatch, tmp_path
):
    actions = []
    notifications = []

    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd):
        actions.append((plan.argv, cwd))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    app_class = _patch_textual_app_class(
        monkeypatch,
        lambda self: (self.action_launch_dry_run(), actions.append(type(self).__name__)),
    )
    monkeypatch.setattr(app_class, "notify", lambda self, message: notifications.append(message))

    assert cli_main(["ui", "--profile", "security"]) == 0

    assert actions[0][0] == ("revrem", "--profile", "security", "--dry-run")
    assert actions[0][1] == tmp_path
    assert actions[1] == "RevRemApp"
    assert notifications == ["Dry run completed: security"]


def test_tui_live_run_action_requires_confirmation_and_starts_controller(monkeypatch, tmp_path):
    notifications = []
    starts = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[profiles.final-pr]\ndescription = "Final PR"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_start(**kwargs):
        starts.append(kwargs)
        return types.SimpleNamespace(artifact_dir_arg=".revrem/runs/live")

    def fake_run(self):
        self.live_run_controller.start = fake_start
        self.action_launch_run()
        self.action_launch_run()

    app_class = _patch_textual_app_class(monkeypatch, fake_run)
    monkeypatch.setattr(app_class, "notify", lambda self, message: notifications.append(message))

    assert cli_main(["ui", "--profile", "final-pr"]) == 0

    assert notifications == [
        "Press r again to start an experimental live run: final-pr",
        "Live run started: final-pr (.revrem/runs/live)",
    ]
    assert len(starts) == 1
    assert starts[0]["plan"].argv == ("revrem", "--profile", "final-pr")
    assert starts[0]["plan"].mode == "run"
    assert starts[0]["cwd"] == tmp_path
    assert starts[0]["entrypoint_resolver"] is tui.current_entrypoint_argv


def test_tui_live_run_action_catches_startup_oserror_and_keeps_setup_failed_state(
    monkeypatch, tmp_path
):
    notifications = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[profiles.final-pr]\ndescription = "Final PR"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    app = tui.RevRemApp(
        model=tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="final-pr"),
        profiles_by_name={
            profile.name: profile
            for profile in tui.profiles.resolve_profiles(
                cwd=tmp_path,
                require_implemented=False,
                include_builtins=True,
            )
        },
    )
    monkeypatch.setattr(
        app, "notify", lambda message: notifications.append(message), raising=False
    )
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    original_start = app.live_run_controller.start

    def fake_start(**kwargs):
        def boom_popen(*_args, **_kwargs):
            raise OSError("revrem not found")

        return original_start(popen_factory=boom_popen, **kwargs)

    app.live_run_controller.start = fake_start

    app.action_launch_run()
    app.action_launch_run()

    assert notifications == [
        "Press r again to start an experimental live run: final-pr",
        "failed to start live run: revrem not found",
    ]
    assert app.live_run_controller.status == "setup-failed"
    assert app.live_run_controller.message == "failed to start live run: revrem not found"
    assert app._pending_live_confirmation_profile is None
    assert app._workspace == "loop"
    assert app._focused_pane == "left"

    run_monitor_updates = [
        value for selector, value in widgets.updates if selector == "#screen-run-monitor"
    ]
    assert run_monitor_updates
    assert "Loop Detail" in run_monitor_updates[-1]
    assert "Live status: setup-failed" not in run_monitor_updates[-1]
    assert "failed to start live run: revrem not found" not in run_monitor_updates[-1]
    assert ("#status-bar", "status-setup-failed") in widgets.classes


def test_tui_live_run_action_refuses_second_r_while_run_is_active(monkeypatch, tmp_path):
    notifications = []
    starts = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[profiles.final-pr]\ndescription = "Final PR"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    app = tui.RevRemApp(
        model=tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="final-pr"),
        profiles_by_name={
            profile.name: profile
            for profile in tui.profiles.resolve_profiles(
                cwd=tmp_path,
                require_implemented=False,
                include_builtins=True,
            )
        },
    )
    monkeypatch.setattr(
        app, "notify", lambda message: notifications.append(message), raising=False
    )

    def fake_start(**kwargs):
        starts.append(kwargs)
        return types.SimpleNamespace(artifact_dir_arg=".revrem/runs/live")

    app.live_run_controller.start = fake_start

    app.action_launch_run()
    app.live_run_controller.process = types.SimpleNamespace(poll=lambda: None)
    app.action_launch_run()

    assert notifications == [
        "Press r again to start an experimental live run: final-pr",
        "Live run is already active. Press k to cancel it.",
    ]
    assert starts == []
    assert app._pending_live_confirmation_profile is None


def test_tui_live_run_action_refuses_second_r_while_run_is_cancelling(
    monkeypatch, tmp_path
):
    notifications = []
    starts = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[profiles.final-pr]\ndescription = "Final PR"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    app = tui.RevRemApp(
        model=tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="final-pr"),
        profiles_by_name={
            profile.name: profile
            for profile in tui.profiles.resolve_profiles(
                cwd=tmp_path,
                require_implemented=False,
                include_builtins=True,
            )
        },
    )
    monkeypatch.setattr(
        app, "notify", lambda message: notifications.append(message), raising=False
    )

    def fake_start(**kwargs):
        starts.append(kwargs)
        return types.SimpleNamespace(artifact_dir_arg=".revrem/runs/live")

    app.live_run_controller.start = fake_start

    app.action_launch_run()
    app._cancel_in_progress = True
    app.action_launch_run()

    assert notifications == [
        "Press r again to start an experimental live run: final-pr",
        "Live run cancellation is already in progress.",
    ]
    assert starts == []
    assert app._pending_live_confirmation_profile is None


def test_tui_edit_profile_refreshes_profile_cache_before_next_live_launch(monkeypatch, tmp_path):
    notifications = []
    launched_artifact_dirs = []

    home = tmp_path / "home"
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)

    def write_profile(artifact_dir: str) -> None:
        config_path.write_text(
            f"""
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.output]
artifact_dir = "{artifact_dir}"
""",
            encoding="utf-8",
        )

    write_profile("artifacts/old")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        if plan.mode == "edit":
            write_profile("artifacts/new")
        return types.SimpleNamespace(returncode=0)

    def fake_start(**kwargs) -> types.SimpleNamespace:
        profile = kwargs["profile"]
        launched_artifact_dirs.append(profile.output.artifact_dir)
        return types.SimpleNamespace(artifact_dir_arg=profile.output.artifact_dir)

    app = tui.RevRemApp(
        model=tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="final-pr"),
        profiles_by_name={
            profile.name: profile
            for profile in tui.profiles.resolve_profiles(
                cwd=tmp_path,
                require_implemented=False,
                include_builtins=True,
            )
        },
    )
    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message), raising=False)
    app.live_run_controller.start = fake_start

    app.action_edit_profile()
    app.action_launch_run()
    app.action_launch_run()

    assert notifications == [
        "Edited profile: final-pr",
        "Press r again to start an experimental live run: final-pr",
        "Live run started: final-pr (artifacts/new)",
    ]
    assert launched_artifact_dirs == ["artifacts/new"]


def test_tui_edit_profile_keeps_current_session_on_invalid_profile_toml(monkeypatch, tmp_path):
    notifications = []
    launched_artifact_dirs = []

    home = tmp_path / "home"
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)

    def write_profile(artifact_dir: str) -> None:
        config_path.write_text(
            f"""
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.output]
artifact_dir = "{artifact_dir}"
""",
            encoding="utf-8",
        )

    def write_invalid_profile() -> None:
        config_path.write_text("[profiles.final-pr\n", encoding="utf-8")

    write_profile("artifacts/old")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        if plan.mode == "edit":
            write_invalid_profile()
        return types.SimpleNamespace(returncode=0)

    def fake_start(**kwargs) -> types.SimpleNamespace:
        profile = kwargs["profile"]
        launched_artifact_dirs.append(profile.output.artifact_dir)
        return types.SimpleNamespace(artifact_dir_arg=profile.output.artifact_dir)

    app = tui.RevRemApp(
        model=tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="final-pr"),
        profiles_by_name={
            profile.name: profile
            for profile in tui.profiles.resolve_profiles(
                cwd=tmp_path,
                require_implemented=False,
                include_builtins=True,
            )
        },
    )
    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message), raising=False)
    app.live_run_controller.start = fake_start

    app.action_edit_profile()
    assert any(
        "Profile refresh skipped: invalid profile config on disk; "
        "keeping current in-session profile state." in message
        for message in notifications
    )
    assert app.profiles_by_name["final-pr"].output.artifact_dir == "artifacts/old"

    app.action_launch_run()
    app.action_launch_run()
    assert launched_artifact_dirs == ["artifacts/old"]
    assert notifications[-1].endswith("final-pr (artifacts/old)")


def test_tui_live_monitor_refresh_updates_run_monitor_widget(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    run_dir = repo / ".revrem" / "runs" / "live"
    run_dir.mkdir(parents=True)
    sink = tui.tui_run_controller.events.JsonlSink(run_dir, "live")
    sink.emit("phase_start", phase="review", iteration=1, payload={"message": "reviewing"})
    sink.close()
    app.live_run_controller.launch = tui.tui_run_controller.LiveRunLaunch(
        argv=("revrem",),
        artifact_dir_arg=".revrem/runs/live",
        artifact_dir=run_dir,
    )
    app.live_run_controller.status = "running"
    app._workspace = "run"
    app._focused_pane = "right"
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app._render_live_monitor()

    updates = {
        selector: value
        for selector, value in widgets.updates
        if selector in {"#screen-home", "#screen-run-monitor"}
    }
    classes = {
        selector: value
        for selector, value in widgets.classes
        if selector in {"#screen-home", "#screen-run-monitor"}
    }
    assert "Run Timeline" in updates["#screen-home"]
    assert "Live status: running" in updates["#screen-run-monitor"]
    assert "0001|review|1|phase_start: reviewing" in updates["#screen-run-monitor"]
    assert classes["#screen-home"] == "panel panel-muted"
    assert classes["#screen-run-monitor"] == "panel panel-focused"


def test_tui_live_monitor_does_not_override_workspace_or_focus(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    run_dir = repo / ".revrem" / "runs" / "live"
    run_dir.mkdir(parents=True)
    sink = tui.tui_run_controller.events.JsonlSink(run_dir, "live")
    sink.emit("phase_start", phase="review", iteration=1, payload={"message": "reviewing"})
    sink.close()
    app.live_run_controller.launch = tui.tui_run_controller.LiveRunLaunch(
        argv=("revrem",),
        artifact_dir_arg=".revrem/runs/live",
        artifact_dir=run_dir,
    )
    app.live_run_controller.status = "running"
    app._workspace = "profiles"
    app._focused_pane = "left"
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app._render_live_monitor()

    updates = {
        selector: value
        for selector, value in widgets.updates
        if selector == "#screen-run-monitor"
    }
    assert "Profile Detail" in updates["#screen-run-monitor"]
    assert "Live status: running" not in updates["#screen-run-monitor"]
    assert app._workspace == "profiles"
    assert app._focused_pane == "left"


def test_tui_live_monitor_escapes_markup_in_event_detail(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    run_dir = repo / ".revrem" / "runs" / "live"
    run_dir.mkdir(parents=True)
    sink = tui.tui_run_controller.events.JsonlSink(run_dir, "live")
    sink.emit("phase_start", phase="review", iteration=1, payload={"message": "[bold]danger[/bold]"})
    sink.close()
    app.live_run_controller.launch = tui.tui_run_controller.LiveRunLaunch(
        argv=("revrem",),
        artifact_dir_arg=".revrem/runs/live",
        artifact_dir=run_dir,
    )
    app.live_run_controller.status = "running"
    app._workspace = "run"
    app._focused_pane = "right"
    updates = []

    class FakeWidget:
        def update(self, value):
            updates.append(value)

    monkeypatch.setattr(app, "query_one", lambda selector: FakeWidget())

    app._render_live_monitor()

    assert updates
    # Untrusted event detail must be escaped, not interpreted as Rich markup.
    assert "\\[bold\\]danger\\[/bold\\]" in updates[0]
    assert "[bold]danger[/bold]" not in updates[0]


def test_tui_run_workspace_render_uses_tuple_stdout_stderr_tails_without_crash(tmp_path):
    model = tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    app.live_run_controller.stdout_tail = ("line-1", "line-2")
    app.live_run_controller.stderr_tail = ("err-1",)
    app.live_run_controller.status = "completed-clear"
    app._workspace = "run"

    app._selected_run_tab_index = 1
    stdout_markup = tui._run_workspace_markup(app)
    assert "view: stdout" in stdout_markup
    assert "line-1" in stdout_markup
    assert "line-2" in stdout_markup

    app._selected_run_tab_index = 2
    stderr_markup = tui._run_workspace_markup(app)
    assert "view: stderr" in stderr_markup
    assert "err-1" in stderr_markup


def test_tui_run_workspace_render_uses_live_stdout_stderr_buffers_while_running(tmp_path):
    model = tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    app._workspace = "run"
    app.live_run_controller.status = "running"
    app.live_run_controller.process = types.SimpleNamespace(poll=lambda: None)
    app.live_run_controller._stdout_buffer.append("line-live-1")
    app.live_run_controller._stderr_buffer.append("err-live-1")

    app._selected_run_tab_index = 1
    stdout_markup = tui._run_workspace_markup(app)
    assert "view: stdout" in stdout_markup
    assert "line-live-1" in stdout_markup

    app._selected_run_tab_index = 2
    stderr_markup = tui._run_workspace_markup(app)
    assert "view: stderr" in stderr_markup
    assert "err-live-1" in stderr_markup


def test_tui_compact_profiles_markup_truncates_description_and_source(tmp_path):
    config_path = tmp_path / ".revrem.toml"
    config_path.write_text(
        """
[profiles.dogfood]
description = "Project-local RevRem dogfood run with full verification, commits, diagnostics, and explicit phase models."

[profiles.dogfood.pipeline]
base = "main"
checks = ["pytest -q"]
""",
        encoding="utf-8",
    )
    model = tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="dogfood")
    app = tui.RevRemApp(model=model, profiles_by_name={})

    markup = tui._profiles_markup(app)

    assert "> dogfood" in markup
    assert "Project-local RevRem dogfood run with ful..." in markup
    assert str(config_path) not in markup
    assert "project" in markup


def test_tui_workspace_switching_updates_two_pane_workbench(monkeypatch, tmp_path):
    model = tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_workspace_loop()

    assert app._workspace == "loop"
    assert app._focused_pane == "left"
    updates = dict(widgets.updates)
    assert "Loop Phases" in updates["#screen-home"]
    assert "Loop Detail" in updates["#screen-run-monitor"]
    assert "workspace=loop" in updates["#status-bar"]


def test_tui_profile_selection_moves_command_preview(monkeypatch, tmp_path):
    config_path = tmp_path / ".revrem.toml"
    config_path.write_text(
        """
[profiles.alpha]
description = "Alpha"

[profiles.beta]
description = "Beta"
""",
        encoding="utf-8",
    )
    model = tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="alpha")
    app = tui.RevRemApp(
        model=model,
        profiles_by_name={
            profile.name: profile
            for profile in tui.profiles.resolve_profiles(
                cwd=tmp_path,
                require_implemented=False,
                include_builtins=True,
            )
        },
    )
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_workspace_profiles()
    app.action_move_down()
    app.action_select()

    assert app._profile_name() == "beta"
    updates = dict(widgets.updates)
    assert "revrem --profile beta" in updates["#status-bar"]
    assert "> [status-info]beta[/]" in updates["#screen-home"]


def test_tui_focus_toggle_updates_panel_classes(monkeypatch, tmp_path):
    model = tui.tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_focus_next()

    assert app._focused_pane == "right"
    assert ("#screen-home", "panel panel-muted") in widgets.classes
    assert ("#screen-run-monitor", "panel panel-focused") in widgets.classes


def test_tui_cancel_action_routes_to_controller(monkeypatch, tmp_path):
    notifications = []
    workers = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    app.live_run_controller.launch = tui.tui_run_controller.LiveRunLaunch(
        argv=("revrem",),
        artifact_dir_arg=".revrem/runs/live",
        artifact_dir=repo / ".revrem" / "runs" / "live",
    )
    app.live_run_controller.process = types.SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(app.live_run_controller, "cancel", lambda: "cancelled")
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))
    monkeypatch.setattr(app, "run_worker", lambda target, thread=True: workers.append((target, thread)))
    monkeypatch.setattr(app, "call_from_thread", lambda callback: callback())

    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_cancel_run()

    assert notifications == ["Live run cancellation requested."]
    assert workers and workers[0][1] is True
    assert app._cancel_in_progress is True
    workers[0][0]()
    assert notifications == [
        "Live run cancellation requested.",
        "Live run cancel completed: cancelled",
    ]
    assert app._cancel_in_progress is False
    assert any(selector == "#screen-run-monitor" for selector, _ in widgets.updates)


def test_tui_cancel_action_reports_when_no_run_is_active(monkeypatch, tmp_path):
    notifications = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_cancel_run()

    assert notifications == ["No active live run to cancel."]
    updates = [value for selector, value in widgets.updates if selector == "#footer-bar"]
    assert any("live: idle" in update for update in updates)


def test_tui_quit_warns_before_cancelling_active_run(monkeypatch, tmp_path):
    notifications = []
    exits = []
    workers = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    app.live_run_controller.process = types.SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(app.live_run_controller, "cancel", lambda: "cancelled")
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))
    monkeypatch.setattr(app, "run_worker", lambda target, thread=True: workers.append(target))
    monkeypatch.setattr(app, "call_from_thread", lambda callback: callback())
    monkeypatch.setattr(app, "exit", lambda: exits.append(True))
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_quit()

    assert notifications == ["Live run is active. Press q again to cancel it and quit."]
    assert exits == []
    assert workers == []
    assert app._quit_confirmation_pending is True

    app.action_quit()
    assert notifications[-1] == "Live run cancellation requested."
    assert len(workers) == 1
    workers[0]()

    assert notifications[-1] == "Live run cancel completed: cancelled"
    assert exits == [True]
    assert app._quit_confirmation_pending is False


def test_tui_quit_without_active_run_exits_immediately(monkeypatch, tmp_path):
    exits = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    monkeypatch.setattr(app, "exit", lambda: exits.append(True))

    app.action_quit()

    assert exits == [True]


def test_tui_refresh_stops_after_terminal_status(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    app.live_run_controller.status = "completed-clear"
    monkeypatch.setattr(
        app.live_run_controller,
        "refresh",
        lambda: (_ for _ in ()).throw(AssertionError("refresh should not run")),
    )

    app._refresh_live_run()


def test_tui_refresh_stops_while_cancel_is_in_progress(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    app.live_run_controller.status = "running"
    app._cancel_in_progress = True
    monkeypatch.setattr(
        app.live_run_controller,
        "refresh",
        lambda: (_ for _ in ()).throw(AssertionError("refresh should not run")),
    )

    app._refresh_live_run()


def test_tui_clear_focus_action_clears_input_focus(monkeypatch, tmp_path):
    notifications = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))
    app._focused_pane = "right"

    app.action_clear_focus()

    assert app._focused_pane == "left"
    assert notifications == ["Focus returned to navigation."]


def test_tui_help_toggle_updates_help_and_status_widgets(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})

    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app.action_toggle_help()

    assert app._help_visible is True
    updates = [value for _, value in widgets.updates]
    classes = [value for _, value in widgets.classes]
    assert any("Run: \\[d] dry-run selected profile" in update for update in updates)
    assert any("? hide help" in update for update in updates)
    assert "status-idle" in classes


def test_tui_help_key_handler_stops_event_and_toggles_help(monkeypatch, tmp_path):
    stopped = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)
    event = types.SimpleNamespace(key="h", stop=lambda: stopped.append(True))

    app.on_key(event)

    assert stopped == [True]
    assert app._help_visible is True
    updates = [value for _, value in widgets.updates]
    assert any("confirm/start live run" in update for update in updates)


def test_tui_edit_action_launches_profile_editor_with_suspended_app(monkeypatch, tmp_path):
    actions = []
    notifications = []

    config_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[profiles.final-pr]\ndescription = "Final PR"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    class FakeSuspend:
        def __enter__(self):
            actions.append("suspend-enter")

        def __exit__(self, exc_type, exc, tb):
            actions.append("suspend-exit")
            return False

    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        actions.append((plan.argv, cwd, capture_output))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    app_class = _patch_textual_app_class(
        monkeypatch,
        lambda self: (self.action_edit_profile(), actions.append(type(self).__name__)),
    )
    monkeypatch.setattr(app_class, "suspend", lambda self: FakeSuspend())
    monkeypatch.setattr(app_class, "notify", lambda self, message: notifications.append(message))

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
    config_path.write_text('[profiles.final-pr]\ndescription = "Final PR"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        actions.append((plan.argv, cwd, capture_output))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)

    def fake_prompt(self, *, title, prompt, initial, on_submit):
        del prompt, initial
        if title == "Clone profile":
            on_submit("copy")
        elif title == "New profile":
            on_submit("fresh")
        elif title == "Import profiles":
            on_submit("/tmp/profiles.toml")
        else:
            raise AssertionError(f"unexpected prompt: {title}")

    app_class = _patch_textual_app_class(
        monkeypatch,
        lambda self: (
            self.action_new_profile(),
            self.action_clone_profile(),
            self.action_import_profiles(),
            self.action_delete_profile(),
            actions.append(type(self).__name__),
        ),
    )
    monkeypatch.setattr(app_class, "_prompt_for_text", fake_prompt)
    monkeypatch.setattr(app_class, "notify", lambda self, message: notifications.append(message))

    assert cli_main(["ui", "--profile", "final-pr"]) == 0

    assert actions[:4] == [
        (("revrem", "config", "new", "fresh", "--no-interactive"), tmp_path, True),
        (("revrem", "config", "clone", "final-pr", "copy"), tmp_path, True),
        (("revrem", "config", "import", "/tmp/profiles.toml"), tmp_path, True),
        (("revrem", "config", "delete", "final-pr", "--yes"), tmp_path, True),
    ]
    assert actions[4] == "RevRemApp"
    assert notifications == [
        "Created profile: fresh",
        "Cloned profile: final-pr -> copy",
        "Imported profiles: /tmp/profiles.toml",
        "Deleted profile: final-pr",
    ]


def test_tui_prompt_cancellation_does_not_run_command(monkeypatch, tmp_path):
    notifications = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

    class Prompt:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    pushed = []
    monkeypatch.setattr(tui, "text_prompt_screen_class", lambda: Prompt)
    monkeypatch.setattr(
        app,
        "push_screen",
        lambda screen, callback: (pushed.append(screen), callback(None)),
        raising=False,
    )
    monkeypatch.setattr(
        app,
        "_run_captured",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    app.action_new_profile()

    assert pushed
    assert notifications == ["New profile cancelled."]


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


def test_run_launch_plan_uses_module_entrypoint_when_console_script_is_missing(
    tmp_path, monkeypatch
):
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


def _run_cli_with_broken_textual(
    tmp_path: Path, *argv: str
) -> subprocess.CompletedProcess[str]:
    return _run_python_with_broken_textual(
        tmp_path,
        "import sys; from code_review_loop.__main__ import main; raise SystemExit(main(sys.argv[1:]))",
        *argv,
    )


def _run_python_with_broken_textual(
    tmp_path: Path,
    code: str,
    *argv: str,
    sentinel: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_site = tmp_path / "fake_site"
    textual_package = fake_site / "textual"
    textual_package.mkdir(parents=True)
    (textual_package / "__init__.py").write_text("", encoding="utf-8")
    app_code = ""
    if sentinel is not None:
        app_code = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('imported')\n"
    app_code += 'raise RuntimeError("broken textual app import")\n'
    (textual_package / "app.py").write_text(app_code, encoding="utf-8")
    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath_entries = [str(fake_site), str(_REPO_ROOT / "src")]
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(pythonpath_entries)}
    return subprocess.run(
        [sys.executable, "-c", code, *argv],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
