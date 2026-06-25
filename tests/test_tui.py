from __future__ import annotations

import importlib.util
import types

from code_review_loop import tui
from code_review_loop.cli.main import main as cli_main


class _WidgetProbe:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str]] = []
        self.classes: list[tuple[str, str]] = []

    def query_one(self, selector: str):
        if selector not in {"#screen-run-monitor", "#screen-controls", "#screen-help", "#status-bar"}:
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
    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    assert cli_main(["ui", "--profile", "missing"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: profile not found: missing" in captured.err


def test_tui_launches_textual_app_with_home_snapshot(monkeypatch, tmp_path):
    rendered = []
    launched = []

    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run(self):
        launched.append(type(self).__name__)
        rendered.append(tui.tui_state.render_shell_text(self.model))

    monkeypatch.setattr(tui.RevRemApp, "run", fake_run)

    assert cli_main(["ui"]) == 0

    assert launched == ["RevRemApp"]
    assert f"Workspace: {tmp_path}" in rendered[0]
    assert "[b]Home[/b]" in rendered[0]
    assert "[b]Profiles[/b]" in rendered[0]
    assert "[b]Pipeline[/b]" in rendered[0]
    assert "[b]Run Monitor[/b]" in rendered[0]


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

    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd):
        actions.append((plan.argv, cwd))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    monkeypatch.setattr(
        tui.RevRemApp,
        "run",
        lambda self: (self.action_launch_dry_run(), actions.append(type(self).__name__)),
    )
    monkeypatch.setattr(tui.RevRemApp, "notify", lambda self, message: notifications.append(message))

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

    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd):
        actions.append((plan.argv, cwd))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    monkeypatch.setattr(
        tui.RevRemApp,
        "run",
        lambda self: (self.action_launch_dry_run(), actions.append(type(self).__name__)),
    )
    monkeypatch.setattr(tui.RevRemApp, "notify", lambda self, message: notifications.append(message))

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
    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_start(**kwargs):
        starts.append(kwargs)
        return types.SimpleNamespace(artifact_dir_arg=".revrem/runs/live")

    def fake_run(self):
        self.live_run_controller.start = fake_start
        self.action_launch_run()
        self.action_launch_run()

    monkeypatch.setattr(tui.RevRemApp, "run", fake_run)
    monkeypatch.setattr(tui.RevRemApp, "notify", lambda self, message: notifications.append(message))

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

    run_monitor_updates = [
        value for selector, value in widgets.updates if selector == "#screen-run-monitor"
    ]
    assert run_monitor_updates
    assert "Live status: setup-failed" in run_monitor_updates[-1]
    assert "failed to start live run: revrem not found" in run_monitor_updates[-1]
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
    widgets = _WidgetProbe()
    monkeypatch.setattr(app, "query_one", widgets.query_one)

    app._render_live_monitor()

    updates = [value for selector, value in widgets.updates if selector == "#screen-run-monitor"]
    assert updates
    assert "Live status: running" in updates[0]
    assert "0001|review|1|phase_start: reviewing" in updates[0]


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
    updates = [value for selector, value in widgets.updates if selector == "#screen-controls"]
    assert any("idle: press r twice to start" in update for update in updates)


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
    focused = []
    notifications = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    model = tui.tui_state.build_shell_model(cwd=repo, selected_profile_name="security")
    app = tui.RevRemApp(model=model, profiles_by_name={})
    monkeypatch.setattr(app, "set_focus", lambda value: focused.append(value))
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

    app.action_clear_focus()

    assert focused == [None]
    assert notifications == ["Input focus cleared."]


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
    assert any("help open" in update for update in updates)
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

    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        actions.append((plan.argv, cwd, capture_output))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    monkeypatch.setattr(
        tui.RevRemApp,
        "run",
        lambda self: (self.action_edit_profile(), actions.append(type(self).__name__)),
    )
    monkeypatch.setattr(tui.RevRemApp, "suspend", lambda self: FakeSuspend())
    monkeypatch.setattr(tui.RevRemApp, "notify", lambda self, message: notifications.append(message))

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

    class FakeInput:
        def __init__(self, value):
            self.value = value

    monkeypatch.setattr(
        tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None
    )
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    def fake_run_launch_plan(plan, *, cwd, capture_output=True):
        actions.append((plan.argv, cwd, capture_output))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)
    monkeypatch.setattr(
        tui.RevRemApp,
        "run",
        lambda self: (
            self.action_clone_profile(),
            self.action_delete_profile(),
            actions.append(type(self).__name__),
        ),
    )
    monkeypatch.setattr(
        tui.RevRemApp,
        "query_one",
        lambda self, selector: FakeInput("copy") if selector == "#profile-name" else None,
    )
    monkeypatch.setattr(tui.RevRemApp, "notify", lambda self, message: notifications.append(message))

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
