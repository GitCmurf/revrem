"""Optional Textual TUI entry point for RevRem."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from code_review_loop import profiles, tui_run_controller, tui_state

INSTALL_HINT = "Install it with: python -m pip install 'revrem[tui]'"
_TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None
if _TEXTUAL_AVAILABLE:
    textual_app = importlib.import_module("textual.app")
    textual_binding = importlib.import_module("textual.binding")
    containers = importlib.import_module("textual.containers")
    widgets = importlib.import_module("textual.widgets")
    _AppBase: Any = textual_app.App
    _Binding: Any | None = getattr(textual_binding, "Binding", None)
    _Header: Any = widgets.Header
    _Footer: Any = widgets.Footer
    _Static: Any = widgets.Static
    _Horizontal: Any | None = getattr(containers, "Horizontal", None)
    _Vertical: Any | None = getattr(containers, "Vertical", None)
    _Input: Any | None = getattr(widgets, "Input", None)
    _TabbedContent: Any | None = getattr(widgets, "TabbedContent", None)
    _TabPane: Any | None = getattr(widgets, "TabPane", None)
else:
    _AppBase = object
    _Binding = None
    _Header = object
    _Footer = object
    _Static = object
    _Horizontal = None
    _Vertical = None
    _Input = None
    _TabbedContent = None
    _TabPane = None


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.dry_run:
        print("RevRem TUI entry point is available.")
        return 0
    if importlib.util.find_spec("textual") is None:
        print(
            f"ERROR: revrem ui requires the optional Textual dependency. {INSTALL_HINT}",
            file=sys.stderr,
        )
        return 1
    try:
        run_textual_app(selected_profile_name=args.profile)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem ui",
        description="Launch the optional RevRem Textual interface.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the TUI entry point without importing or launching Textual.",
    )
    parser.add_argument(
        "--profile",
        help="Select the initial profile shown in the TUI.",
    )
    return parser.parse_args(argv)


def run_textual_app(*, selected_profile_name: str | None = None) -> None:
    model = tui_state.build_shell_model(cwd=Path.cwd(), selected_profile_name=selected_profile_name)
    profiles_by_name = {
        profile.name: profile
        for profile in profiles.resolve_profiles(
            cwd=Path(model.snapshot.cwd),
            require_implemented=False,
            include_builtins=True,
        )
    }
    RevRemApp(model=model, profiles_by_name=profiles_by_name).run()


class RevRemApp(_AppBase):  # type: ignore[misc, valid-type]
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
        padding: 0 1 1 1;
    }

    #status-bar {
        dock: top;
        height: 3;
        padding: 0 2;
        text-style: bold;
    }

    #left-column {
        width: 45%;
        min-width: 34;
        height: 1fr;
    }

    #right-column {
        width: 55%;
        min-width: 42;
        height: 1fr;
    }

    .panel {
        border: round $surface;
        padding: 0 1;
        margin: 0 1 1 0;
    }

    #screen-run-monitor {
        height: 2fr;
    }

    #screen-controls, #screen-help {
        height: 1fr;
    }

    #profile-name, #profile-path {
        margin: 0 0 1 0;
    }

    .panel-title {
        text-style: bold;
    }

    .status-idle {
        color: $text-muted;
    }

    .status-running, .status-starting {
        color: $accent;
    }

    .status-cancelled {
        color: $warning;
    }

    .status-completed-clear {
        color: $success;
    }

    .status-completed-findings, .status-budget {
        color: $warning;
    }

    .status-failed, .status-setup-failed, .status-failed-forced-cleanup,
    .status-interrupted-before-run-initialized {
        color: $error;
    }
    """
    BINDINGS = [
        ("d", "launch_dry_run", "Dry run"),
        ("r", "launch_run", "Run"),
        ("k", "cancel_run", "Cancel run"),
        (
            _Binding("question_mark", "toggle_help", "Help", priority=True)
            if _Binding is not None
            else ("question_mark", "toggle_help", "Help")
        ),
        (
            _Binding("h", "toggle_help", "Help", priority=True)
            if _Binding is not None
            else ("h", "toggle_help", "Help")
        ),
        ("tab", "focus_next", "Focus next"),
        ("shift+tab", "focus_previous", "Focus previous"),
        ("s", "show_profile", "Show"),
        ("e", "edit_profile", "Edit profile"),
        ("n", "new_profile", "New"),
        ("c", "clone_profile", "Clone"),
        ("x", "export_profile", "Export"),
        ("i", "import_profiles", "Import"),
        ("delete", "delete_profile", "Delete"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        model: tui_state.TuiShellModel,
        profiles_by_name: dict[str, profiles.Profile],
    ) -> None:
        super().__init__()
        self.model = model
        self.profiles_by_name = profiles_by_name
        self.live_run_controller = tui_run_controller.LiveRunController()
        self._pending_live_confirmation_profile: str | None = None
        self._help_visible = False
        self._cancel_in_progress = False
        self._quit_confirmation_pending = False

    def compose(self):
        yield _Header(show_clock=True)
        if _Horizontal is not None and _Vertical is not None:
            yield _Static(
                _status_bar_markup(self),
                id="status-bar",
                classes=_status_bar_classes(self.live_run_controller.status),
                markup=True,
            )
            with _Horizontal(id="body"):
                with _Vertical(id="left-column"):
                    for screen_name in ("home", "profiles", "pipeline"):
                        screen = _screen_by_name(self.model, screen_name)
                        if screen is not None:
                            yield _Static(
                                _screen_markup(screen),
                                id=f"screen-{screen.name}",
                                classes="panel",
                                markup=True,
                            )
                with _Vertical(id="right-column"):
                    screen = _screen_by_name(self.model, "run-monitor")
                    if screen is not None:
                        yield _Static(
                            _screen_markup(screen),
                            id=f"screen-{screen.name}",
                            classes="panel",
                            markup=True,
                        )
                    if _Input is not None:
                        yield _Input(
                            value=self.model.selected_profile_name or "",
                            placeholder="profile name",
                            id="profile-name",
                        )
                        yield _Input(
                            placeholder="import path",
                            id="profile-path",
                        )
                    yield _Static(
                        _controls_markup(self),
                        id="screen-controls",
                        classes="panel",
                        markup=True,
                    )
                    yield _Static(
                        _help_markup(visible=False),
                        id="screen-help",
                        classes="panel",
                        markup=True,
                    )
        elif _TabbedContent is not None and _TabPane is not None:
            with _TabbedContent():
                for screen in self.model.screens:
                    with _TabPane(screen.title):
                        yield _Static(_screen_markup(screen), id=f"screen-{screen.name}", markup=True)
                with _TabPane("Controls"):
                    if _Input is not None:
                        yield _Input(
                            value=self.model.selected_profile_name or "",
                            placeholder="profile name",
                            id="profile-name",
                        )
                        yield _Input(
                            placeholder="import path",
                            id="profile-path",
                        )
                    yield _Static(
                        _controls_markup(self),
                        id="screen-controls",
                        markup=True,
                    )
        else:
            yield _Static(
                tui_state.render_shell_text(self.model),
                id="body",
                markup=True,
            )
        yield _Footer()

    def on_mount(self) -> None:
        set_focus = getattr(self, "set_focus", None)
        if callable(set_focus):
            set_focus(None)
        set_interval = getattr(self, "set_interval", None)
        if callable(set_interval):
            set_interval(0.5, self._refresh_live_run)

    def on_key(self, event: Any) -> None:
        if getattr(event, "key", None) not in {"?", "question_mark", "h"}:
            return
        stop = getattr(event, "stop", None)
        if callable(stop):
            stop()
        self.action_toggle_help()

    def action_launch_dry_run(self) -> None:
        profile_name = self._profile_name()
        selected = self._profile_by_name(profile_name)
        if selected is None:
            _notify(self, "No profile is available to dry-run.")
            return
        plan = tui_state.launch_plan(selected, dry_run=True)
        result = run_launch_plan(plan, cwd=Path(self.model.snapshot.cwd))
        if result.returncode == 0:
            _notify(self, f"Dry run completed: {profile_name}")
            return
        _notify(self, f"Dry run failed with exit {result.returncode}: {profile_name}")

    def action_launch_run(self) -> None:
        profile_name = self._profile_name()
        selected = self._profile_by_name(profile_name)
        if selected is None or profile_name is None:
            _notify(self, "No profile is available to run.")
            return
        if self._pending_live_confirmation_profile != profile_name:
            self._pending_live_confirmation_profile = profile_name
            _notify(self, f"Press r again to start an experimental live run: {profile_name}")
            self._update_console_status()
            return
        self._pending_live_confirmation_profile = None
        plan = tui_state.launch_plan(selected, dry_run=False)
        launch = self.live_run_controller.start(
            profile=selected,
            plan=plan,
            cwd=Path(self.model.snapshot.cwd),
            entrypoint_resolver=current_entrypoint_argv,
        )
        _notify(self, f"Live run started: {profile_name} ({launch.artifact_dir_arg})")
        self._render_live_monitor()

    def action_cancel_run(self) -> None:
        self._quit_confirmation_pending = False
        if not self._live_run_active():
            _notify(self, "No active live run to cancel.")
            self._update_console_status()
            return
        self._request_cancel(exit_after=False)

    def action_quit(self) -> None:
        if not self._live_run_active():
            self._exit_app()
            return
        if not self._quit_confirmation_pending:
            self._quit_confirmation_pending = True
            _notify(self, "Live run is active. Press q again to cancel it and quit.")
            self._update_console_status()
            return
        self._request_cancel(exit_after=True)

    def action_toggle_help(self) -> None:
        self._help_visible = not self._help_visible
        _update_widget(self, "#screen-help", _help_markup(visible=self._help_visible))
        self._update_console_status()

    def action_show_profile(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to show.")
            return
        self._run_interactive(
            tui_state.show_plan_for_name(profile_name), success=f"Shown profile: {profile_name}"
        )

    def action_edit_profile(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to edit.")
            return
        self._run_interactive(
            tui_state.edit_plan_for_name(profile_name),
            success=f"Edited profile: {profile_name}",
        )

    def action_new_profile(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "Enter a profile name before creating a profile.")
            return
        self._run_captured(
            tui_state.new_plan_for_name(profile_name),
            success=f"Created profile: {profile_name}",
        )

    def action_clone_profile(self) -> None:
        source = self.model.selected_profile_name
        target = self._profile_name()
        if source is None:
            _notify(self, "No profile is available to clone.")
            return
        if target is None or target == source:
            target = f"{source}-copy"
        self._run_captured(
            tui_state.clone_plan_for_name(source, target),
            success=f"Cloned profile: {source} -> {target}",
        )

    def action_delete_profile(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to delete.")
            return
        self._run_captured(
            tui_state.delete_plan_for_name(profile_name),
            success=f"Deleted profile: {profile_name}",
        )

    def action_export_profile(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to export.")
            return
        self._run_interactive(
            tui_state.export_plan_for_name(profile_name),
            success=f"Exported profile: {profile_name}",
        )

    def action_import_profiles(self) -> None:
        path = self._path_value()
        if path is None:
            _notify(self, "Enter an import path before importing profiles.")
            return
        self._run_captured(tui_state.import_plan_for_path(path), success=f"Imported profiles: {path}")

    def _run_interactive(self, plan: tui_state.LaunchPlan, *, success: str) -> None:
        result = self._run_plan(plan, capture_output=False)
        if result.returncode == 0:
            _notify(self, success)
            return
        _notify(self, f"{plan.mode} failed with exit {result.returncode}: {plan.profile_name}")

    def _run_captured(self, plan: tui_state.LaunchPlan, *, success: str) -> None:
        result = self._run_plan(plan, capture_output=True)
        if result.returncode == 0:
            _notify(self, success)
            return
        _notify(self, f"{plan.mode} failed with exit {result.returncode}: {plan.profile_name}")

    def _run_plan(
        self,
        plan: tui_state.LaunchPlan,
        *,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        suspend = getattr(self, "suspend", None)
        if callable(suspend) and not capture_output:
            with suspend():
                return run_launch_plan(
                    plan, cwd=Path(self.model.snapshot.cwd), capture_output=False
                )
        return run_launch_plan(plan, cwd=Path(self.model.snapshot.cwd), capture_output=capture_output)

    def _profile_name(self) -> str | None:
        value = _input_value(self, "#profile-name")
        if value:
            return value
        return self.model.selected_profile_name

    def _path_value(self) -> str | None:
        return _input_value(self, "#profile-path")

    def _profile_by_name(self, profile_name: str | None) -> Any | None:
        if profile_name is None:
            return None
        return self.profiles_by_name.get(profile_name)

    def _live_run_active(self) -> bool:
        process = self.live_run_controller.process
        return process is not None and process.poll() is None

    def _refresh_live_run(self) -> None:
        if self.live_run_controller.status == "idle":
            return
        if self.live_run_controller.status in tui_run_controller.TERMINAL_STATUSES:
            return
        self.live_run_controller.refresh()
        self._render_live_monitor()

    def _request_cancel(self, *, exit_after: bool) -> None:
        if self._cancel_in_progress:
            _notify(self, "Live run cancellation is already in progress.")
            return
        self._cancel_in_progress = True
        _notify(self, "Live run cancellation requested.")
        self._update_console_status()

        def cancel_and_update() -> None:
            status = self.live_run_controller.cancel()

            def finish_update() -> None:
                self._cancel_in_progress = False
                self._quit_confirmation_pending = False
                _notify(self, f"Live run cancel completed: {status}")
                self._render_live_monitor()
                if exit_after:
                    self._exit_app()

            _call_from_thread(self, finish_update)

        _run_background(self, cancel_and_update)

    def _exit_app(self) -> None:
        exit_app = getattr(self, "exit", None)
        if callable(exit_app):
            exit_app()

    def _render_live_monitor(self) -> None:
        if self.live_run_controller.launch is None:
            self._update_console_status()
            return
        _update_widget(self, "#screen-run-monitor", _live_monitor_markup(self.live_run_controller))
        self._update_console_status()

    def _update_console_status(self) -> None:
        _update_widget(self, "#status-bar", _status_bar_markup(self))
        _update_widget(self, "#screen-controls", _controls_markup(self))
        _set_widget_classes(
            self,
            "#status-bar",
            _status_bar_classes(self.live_run_controller.status),
        )


def _screen_markup(screen: tui_state.TuiScreen) -> str:
    escaped_lines = "\n".join(tui_state.markup_escape(line) for line in screen.lines)
    return f"[b]{tui_state.markup_escape(screen.title)}[/b]\n{escaped_lines}"


def _screen_by_name(model: tui_state.TuiShellModel, name: str) -> tui_state.TuiScreen | None:
    for screen in model.screens:
        if screen.name == name:
            return screen
    return None


def _controls_markup(app: RevRemApp) -> str:
    selected = app._profile_name() or "<none>"
    if app._cancel_in_progress:
        live_hint = "cancelling: waiting for child process to exit"
    elif app._quit_confirmation_pending:
        live_hint = "quit pending: press q again to cancel the run and quit"
    elif app._pending_live_confirmation_profile:
        live_hint = f"confirm run: press r again for {app._pending_live_confirmation_profile}"
    elif app._live_run_active():
        live_hint = "active run: press k to cancel"
    else:
        live_hint = "idle: press r twice to start, d to dry-run"
    return (
        f"[b]Selected[/b]\n{tui_state.markup_escape(selected)}\n\n"
        "[b]Live controls[/b]\n"
        f"{tui_state.markup_escape(live_hint)}\n\n"
        "[b]Essential keys[/b]\n"
        "\\[d]ry-run  \\[r]un  \\[k]cancel  \\[h]help  \\[q]quit\n\n"
        "[b]Profile actions[/b]\n"
        "\\[s]how  \\[e]dit  \\[n]ew  \\[c]lone  e\\[x]port  \\[i]mport  \\[delete]delete"
    )


def _live_monitor_markup(controller: tui_run_controller.LiveRunController) -> str:
    status = controller.status
    lines = [
        "[b]Run Monitor[/b]",
        f"Live status: {tui_state.markup_escape(status)}",
    ]
    if controller.launch is not None:
        lines.append(f"artifacts: {tui_state.markup_escape(str(controller.launch.artifact_dir))}")
    if controller.message:
        lines.append(f"message: {tui_state.markup_escape(controller.message)}")
    snapshot = controller.read_live_events()
    if snapshot.error:
        lines.append(f"events: unavailable ({tui_state.markup_escape(snapshot.error)})")
    elif not snapshot.ready:
        lines.append("events: waiting for events.jsonl")
    else:
        suffix = " [truncated]" if snapshot.truncated else ""
        lines.append(f"events: {len(snapshot.events)} loaded{suffix}")
        for event in tui_state.event_views_from_events(list(snapshot.events))[-8:]:
            phase = event.phase or event.kind
            iteration = "" if event.iteration is None else f"|{event.iteration}"
            detail = f": {event.detail}" if event.detail else ""
            lines.append(f"  {event.seq:04d}|{phase}{iteration}|{event.kind}{detail}")
    return "\n".join(lines)


def _status_bar_markup(app: RevRemApp) -> str:
    profile_name = app._profile_name() or "<none>"
    status = app.live_run_controller.status
    pending = (
        f" | confirm r for {app._pending_live_confirmation_profile}"
        if app._pending_live_confirmation_profile
        else ""
    )
    if app._cancel_in_progress:
        pending = " | cancelling"
    elif app._quit_confirmation_pending:
        pending = " | quit needs confirmation"
    help_state = "help open" if app._help_visible else "h help"
    return (
        f"RevRem | {tui_state.markup_escape(Path(app.model.snapshot.cwd).name or app.model.snapshot.cwd)}"
        f" | profile {tui_state.markup_escape(profile_name)}"
        f" | live {tui_state.markup_escape(status)}{tui_state.markup_escape(pending)}\n"
        f"\\[d]dry-run \\[r]run \\[k]cancel \\[{help_state}] \\[q]quit"
    )


def _status_bar_classes(status: tui_run_controller.RunControllerStatus) -> str:
    return f"status-{status}"


def _help_markup(*, visible: bool) -> str:
    if not visible:
        return "[b]Help[/b]\nPress \\[h] for full keybindings."
    return (
        "[b]Help[/b]\n"
        "Universal: \\[q] quit | \\[Tab] next focus | \\[Shift+Tab] previous focus | \\[h] hide help\n"
        "Run: \\[d] dry-run selected profile | \\[r] confirm/start live run | \\[k] cancel active run\n"
        "Profile: \\[s] show | \\[e] edit | \\[n] new | \\[c] clone | \\[x] export | \\[i] import | \\[delete] delete\n"
        "Fields: profile name targets profile actions; import path targets profile imports."
    )


def _update_widget(app: Any, selector: str, value: str) -> None:
    query_one = getattr(app, "query_one", None)
    if not callable(query_one):
        return
    try:
        widget = query_one(selector)
    except Exception:
        return
    update = getattr(widget, "update", None)
    if callable(update):
        update(value)


def _set_widget_classes(app: Any, selector: str, classes: str) -> None:
    query_one = getattr(app, "query_one", None)
    if not callable(query_one):
        return
    try:
        widget = query_one(selector)
    except Exception:
        return
    set_classes = getattr(widget, "set_classes", None)
    if callable(set_classes):
        set_classes(classes)


def _run_background(app: Any, target: Any) -> None:
    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        run_worker(target, thread=True)
        return
    thread = threading.Thread(target=target, name="revrem-tui-cancel", daemon=True)
    thread.start()


def _call_from_thread(app: Any, callback: Any) -> None:
    call_from_thread = getattr(app, "call_from_thread", None)
    if callable(call_from_thread):
        call_from_thread(callback)
        return
    callback()


def _input_value(app: Any, selector: str) -> str | None:
    query_one = getattr(app, "query_one", None)
    if not callable(query_one):
        return None
    try:
        widget = query_one(selector)
    except Exception:
        return None
    value = getattr(widget, "value", None)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def run_launch_plan(
    plan: tui_state.LaunchPlan,
    *,
    cwd: Path,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    argv = current_entrypoint_argv(plan.argv)
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        capture_output=capture_output,
        check=False,
    )


def current_entrypoint_argv(argv: Sequence[str]) -> list[str]:
    resolved = list(argv)
    if not resolved or resolved[0] != "revrem":
        return resolved
    launcher = Path(sys.argv[0])
    if launcher.name in {"revrem", "code-review-loop"} and launcher.exists():
        resolved[0] = str(launcher)
        return resolved
    if launcher.suffix == ".py":
        # Preserve a runnable entrypoint when the TUI itself was started with `python -m`.
        return [sys.executable, "-m", "code_review_loop", *resolved[1:]]
    return resolved


def _notify(app: Any, message: str) -> None:
    notify = getattr(app, "notify", None)
    if callable(notify):
        notify(message)
    else:
        print(message)
