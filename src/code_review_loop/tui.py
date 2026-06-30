"""Optional Textual TUI entry point for RevRem."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, NamedTuple

from code_review_loop import harnesses, profiles, tui_run_controller, tui_state

INSTALL_HINT = "Install it with: python -m pip install 'revrem[tui]'"
_TEXTUAL_IMPORT_ERROR: Exception | None = None
_TEXTUAL_COMPONENTS: _TextualComponents | None = None
_TEXTUAL_APP_CLASS: type[Any] | None = None
_TEXT_PROMPT_SCREEN_CLASS: type[Any] | None = None
_WORKSPACES = ("loop", "run", "profiles", "prompts")
_PHASES = ("review", "triage", "remediation", "checks", "commit")
_RUN_TABS = ("events", "stdout", "stderr", "summary")
_FOCUS_PANES = ("left", "right")


class _TextualFallbackApp:
    """Test-double-friendly base used when Textual is not importable."""

    def run(self) -> None:
        raise RuntimeError(_textual_unavailable_message())

    def notify(self, _message: str) -> None:
        return None

    def query_one(self, _selector: str) -> Any:
        raise RuntimeError(_textual_unavailable_message())

    def set_focus(self, _value: Any) -> None:
        return None

    def exit(self) -> None:
        return None

    def run_worker(self, target: Any, *, thread: bool = True) -> None:
        del thread
        target()

    def call_from_thread(self, callback: Any) -> None:
        callback()

    def suspend(self) -> Any:
        class _Suspend:
            def __enter__(self) -> None:
                return None

            def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
                del exc_type, exc, tb
                return False

        return _Suspend()


class _TextualComponents(NamedTuple):
    app: Any
    binding: Any
    containers: Any
    screen: Any
    widgets: Any


_Binding: Any | None = None
_Header: Any = object
_Footer: Any = object
_Static: Any = object
_Horizontal: Any | None = None
_Vertical: Any | None = None
_VerticalScroll: Any | None = None
_Input: Any | None = None
_ModalScreen: Any | None = None
_TabbedContent: Any | None = None
_TabPane: Any | None = None


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.dry_run:
        print("RevRem TUI entry point is available.")
        return 0
    if not _textual_can_launch():
        print(_textual_unavailable_message(), file=sys.stderr)
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
        help="Validate the TUI entry point without launching Textual.",
    )
    parser.add_argument(
        "--profile",
        help="Select the initial profile shown in the TUI.",
    )
    return parser.parse_args(argv)


def run_textual_app(*, selected_profile_name: str | None = None) -> None:
    app_class = textual_app_class()
    model = tui_state.build_shell_model(cwd=Path.cwd(), selected_profile_name=selected_profile_name)
    profiles_by_name = {
        profile.name: profile
        for profile in profiles.resolve_profiles(
            cwd=Path(model.snapshot.cwd),
            require_implemented=False,
            include_builtins=True,
        )
    }
    app_class(model=model, profiles_by_name=profiles_by_name).run()


def _textual_unavailable_message() -> str:
    message = f"ERROR: revrem ui requires the optional Textual dependency. {INSTALL_HINT}"
    if _TEXTUAL_IMPORT_ERROR is not None:
        message += (
            " Textual was found but could not be imported: "
            f"{type(_TEXTUAL_IMPORT_ERROR).__name__}: {_TEXTUAL_IMPORT_ERROR}"
        )
    return message


def _textual_can_launch() -> bool:
    if importlib.util.find_spec("textual") is None:
        return False
    return _load_textual_components() is not None


def _load_textual_components() -> _TextualComponents | None:
    global _TEXTUAL_COMPONENTS, _TEXTUAL_IMPORT_ERROR
    if _TEXTUAL_COMPONENTS is not None:
        return _TEXTUAL_COMPONENTS
    if _TEXTUAL_IMPORT_ERROR is not None:
        return None
    if importlib.util.find_spec("textual") is None:
        return None
    try:
        _TEXTUAL_COMPONENTS = _TextualComponents(
            app=importlib.import_module("textual.app"),
            binding=importlib.import_module("textual.binding"),
            containers=importlib.import_module("textual.containers"),
            screen=importlib.import_module("textual.screen"),
            widgets=importlib.import_module("textual.widgets"),
        )
    except Exception as exc:
        _TEXTUAL_IMPORT_ERROR = exc
        return None
    return _TEXTUAL_COMPONENTS


def _install_textual_components(components: _TextualComponents) -> None:
    global _Binding, _Header, _Footer, _Static, _Horizontal, _Vertical, _VerticalScroll
    global _Input, _ModalScreen, _TabbedContent, _TabPane
    _Binding = getattr(components.binding, "Binding", None)
    _Header = components.widgets.Header
    _Footer = components.widgets.Footer
    _Static = components.widgets.Static
    _Horizontal = getattr(components.containers, "Horizontal", None)
    _Vertical = getattr(components.containers, "Vertical", None)
    _VerticalScroll = getattr(components.containers, "VerticalScroll", None)
    _Input = getattr(components.widgets, "Input", None)
    _ModalScreen = getattr(components.screen, "ModalScreen", None)
    _TabbedContent = getattr(components.widgets, "TabbedContent", None)
    _TabPane = getattr(components.widgets, "TabPane", None)


def textual_app_class() -> type[Any]:
    global _TEXTUAL_APP_CLASS
    components = _load_textual_components()
    if components is None:
        raise RuntimeError(_textual_unavailable_message())
    _install_textual_components(components)
    if _TEXTUAL_APP_CLASS is None:
        _TEXTUAL_APP_CLASS = type(
            "RevRemApp",
            (_RevRemAppMixin, components.app.App),
            {"BINDINGS": _build_bindings(_Binding)},
        )
    return _TEXTUAL_APP_CLASS


def text_prompt_screen_class() -> type[Any] | None:
    global _TEXT_PROMPT_SCREEN_CLASS
    components = _load_textual_components()
    if components is None:
        return None
    _install_textual_components(components)
    if _ModalScreen is None or _Input is None or _Vertical is None:
        return None
    if _TEXT_PROMPT_SCREEN_CLASS is None:
        modal_screen: Any = _ModalScreen
        vertical: Any = _Vertical
        static: Any = _Static
        input_widget: Any = _Input

        class TextPrompt(modal_screen):
            BINDINGS = [
                _binding("escape", "cancel", "Cancel", priority=True, binding_cls=_Binding)
            ]

            def __init__(self, *, title: str, prompt: str, initial: str) -> None:
                super().__init__()
                self.prompt_title = title
                self.prompt_text = prompt
                self.initial_value = initial

            def compose(self):
                with vertical(id="prompt-dialog"):
                    yield static(
                        tui_state.markup_escape(self.prompt_title),
                        id="prompt-title",
                        markup=True,
                    )
                    yield static(tui_state.markup_escape(self.prompt_text), markup=True)
                    yield input_widget(value=self.initial_value, id="prompt-input")
                    yield static("Enter submits | Esc cancels")

            def on_mount(self) -> None:
                set_focus = getattr(self, "set_focus", None)
                query_one = getattr(self, "query_one", None)
                if callable(set_focus) and callable(query_one):
                    set_focus(query_one("#prompt-input"))

            def on_input_submitted(self, event: Any) -> None:
                self.dismiss(getattr(event, "value", ""))

            def action_cancel(self) -> None:
                self.dismiss(None)

        _TEXT_PROMPT_SCREEN_CLASS = TextPrompt
    return _TEXT_PROMPT_SCREEN_CLASS


def _binding(
    key: str,
    action: str,
    description: str,
    *,
    priority: bool = False,
    binding_cls: Any | None = None,
) -> Any:
    """Build a Textual Binding, falling back to a plain tuple when Textual's
    Binding class is unavailable (optional dependency not installed)."""
    binding = _Binding if binding_cls is None else binding_cls
    if binding is not None:
        return binding(key, action, description, priority=priority)
    return (key, action, description)


def _build_bindings(binding_cls: Any | None) -> list[Any]:
    return [
        ("1", "workspace_loop", "Loop"),
        ("2", "workspace_run", "Run"),
        ("3", "workspace_profiles", "Profiles"),
        ("4", "workspace_prompts", "Prompts"),
        ("j", "move_down", "Down"),
        ("down", "move_down", "Down"),
        ("up", "move_up", "Up"),
        ("enter", "select", "Select"),
        _binding("space", "toggle_phase", "Toggle phase", priority=True, binding_cls=binding_cls),
        _binding("m", "cycle_harness", "Harness", priority=True, binding_cls=binding_cls),
        _binding("f", "cycle_effort", "Effort", priority=True, binding_cls=binding_cls),
        _binding("M", "edit_model", "Model", priority=True, binding_cls=binding_cls),
        _binding("t", "edit_timeout", "Timeout", priority=True, binding_cls=binding_cls),
        _binding(
            "i",
            "edit_max_iterations",
            "Max iterations",
            priority=True,
            binding_cls=binding_cls,
        ),
        _binding("F", "toggle_final_review", "Final review", priority=True, binding_cls=binding_cls),
        ("d", "launch_dry_run", "Dry run"),
        ("r", "launch_run", "Run"),
        ("k", "cancel_run", "Cancel run"),
        ("l", "toggle_logs", "Logs"),
        ("o", "show_artifacts", "Artifacts"),
        _binding("question_mark", "toggle_help", "Help", priority=True, binding_cls=binding_cls),
        _binding("h", "toggle_help", "Help", priority=True, binding_cls=binding_cls),
        ("tab", "focus_next", "Focus next"),
        ("shift+tab", "focus_previous", "Focus previous"),
        _binding("escape", "clear_focus", "Clear focus", priority=True, binding_cls=binding_cls),
        ("s", "save_loop", "Save"),
        ("e", "edit_profile", "Edit profile"),
        ("n", "new_profile", "New"),
        ("c", "clone_profile", "Clone"),
        ("x", "export_profile", "Export"),
        ("delete", "delete_profile", "Delete"),
        ("q", "quit", "Quit"),
    ]


class _RevRemAppMixin:
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
        padding: 0 1 1 1;
    }

    #loop-pane {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    #run-pane {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    .loop-diagram {
        width: 1fr;
        height: auto;
    }

    .loop-run {
        width: 1fr;
        height: auto;
    }

    .loop-row {
        height: auto;
    }

    .run-row {
        height: auto;
    }

    .phase-gutter {
        width: 44;
        height: auto;
        color: $text-muted;
    }

    .phase-card {
        width: 1fr;
        height: auto;
    }

    .run-phase {
        width: 1fr;
        height: auto;
    }

    .event-log {
        margin-top: 1;
        height: auto;
    }

    .triage-routes-table {
        margin-left: 4;
        height: auto;
    }

    #status-bar {
        dock: top;
        height: 4;
        padding: 0 2;
        text-style: bold;
    }

    #left-pane {
        width: 38%;
        min-width: 34;
        height: 1fr;
    }

    #right-pane {
        width: 62%;
        min-width: 42;
        height: 1fr;
    }

    .panel {
        border: round $surface;
        padding: 0 1;
        margin: 0 1 0 0;
        overflow-y: auto;
    }

    .panel-focused {
        border: round $accent;
    }

    .panel-muted {
        border: round $surface;
        color: $text-muted;
    }

    #footer-bar {
        dock: bottom;
        height: 2;
        padding: 0 2;
        background: $surface;
    }

    .panel-title, .workspace-active {
        text-style: bold;
    }

    .workspace-active {
        color: $accent;
    }

    .status-success {
        color: $success;
    }

    .status-warning {
        color: $warning;
    }

    .status-error {
        color: $error;
    }

    .status-info {
        color: $accent;
    }

    .muted {
        color: $text-muted;
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

    TextPrompt {
        align: center middle;
    }

    #prompt-dialog {
        width: 64;
        height: 9;
        max-width: 90%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    #prompt-title {
        text-style: bold;
    }

    #prompt-input {
        margin: 1 0;
    }
    """
    BINDINGS = _build_bindings(None)

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
        self._workspace: str = "loop"
        self._focused_pane: str = "left"
        self._selected_profile_index = self._initial_profile_index()
        self._selected_phase_index = 0
        self._selected_run_tab_index = 0
        self._loop_diagram = None
        self._loop_model = None
        self._loop_run_view = None
        self._event_log = None

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
                loop_widget = _loop_diagram_widget(self)
                if loop_widget is not None:
                    with _Vertical(id="loop-pane"):
                        yield loop_widget
                run_widget = _loop_run_widget(self)
                event_log = _event_log_widget(self)
                if run_widget is not None and event_log is not None:
                    with _Vertical(id="run-pane"):
                        yield run_widget
                        yield event_log
                with _Vertical(id="left-pane"):
                    yield _panel_widget(
                        _left_pane_markup(self),
                        widget_id="screen-home",
                        focused=self._focused_pane == "left",
                    )
                with _Vertical(id="right-pane"):
                    yield _panel_widget(
                        _right_pane_markup(self),
                        widget_id="screen-run-monitor",
                        focused=self._focused_pane == "right",
                    )
            yield _Static(
                _footer_markup(self),
                id="footer-bar",
                markup=True,
            )
        elif _TabbedContent is not None and _TabPane is not None:
            with _TabbedContent():
                for screen in self.model.screens:
                    with _TabPane(screen.title):
                        yield _Static(
                            _screen_markup_for_app(self, screen),
                            id=f"screen-{screen.name}",
                            markup=True,
                        )
                with _TabPane("Controls"):
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

    def on_mount(self) -> None:
        set_focus = getattr(self, "set_focus", None)
        if callable(set_focus):
            set_focus(None)
        set_interval = getattr(self, "set_interval", None)
        if callable(set_interval):
            set_interval(0.5, self._refresh_live_run)
        self._render_workbench()

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
        if (
            self._workspace == "loop"
            and self._loop_diagram is not None
            and self._loop_diagram.is_dirty
        ):
            try:
                self._loop_diagram.model.save()
            except (OSError, RuntimeError, ValueError) as exc:
                _notify(self, f"Save-and-run aborted: {exc}", severity="error")
                return
            self._refresh_profiles_from_disk()
            self._update_console_status()
            selected = self._profile_by_name(profile_name)
            if selected is None:
                _notify(self, "Saved loop, but refreshed profile is unavailable.")
                return
            _notify(self, f"Saved loop before run: {profile_name}")
        if self._cancel_in_progress:
            self._pending_live_confirmation_profile = None
            _notify(self, "Live run cancellation is already in progress.")
            self._update_console_status()
            return
        if self._live_run_active():
            self._pending_live_confirmation_profile = None
            _notify(self, "Live run is already active. Press k to cancel it.")
            self._update_console_status()
            return
        if self._pending_live_confirmation_profile != profile_name:
            self._pending_live_confirmation_profile = profile_name
            _notify(self, f"Press r again to start an experimental live run: {profile_name}")
            self._update_console_status()
            return
        self._pending_live_confirmation_profile = None
        plan = tui_state.launch_plan(selected, dry_run=False)
        try:
            launch = self.live_run_controller.start(
                profile=selected,
                plan=plan,
                cwd=Path(self.model.snapshot.cwd),
                entrypoint_resolver=current_entrypoint_argv,
            )
        except OSError:
            _notify(self, self.live_run_controller.message or f"Live run failed: {profile_name}")
            self._render_live_monitor()
            return
        self._workspace = "run"
        self._focused_pane = "right"
        _notify(self, f"Live run started: {profile_name} ({launch.artifact_dir_arg})")
        self._render_workbench()
        self._render_live_monitor()

    def action_cancel_run(self) -> None:
        self._quit_confirmation_pending = False
        if not self._live_run_active():
            _notify(self, "No active live run to cancel.")
            self._update_console_status()
            return
        self._request_cancel(exit_after=False)

    def action_toggle_logs(self) -> None:
        if self._workspace != "run" or self._event_log is None:
            return
        self._event_log.show_logs = not self._event_log.show_logs
        self._event_log.rebuild()
        _notify(self, "Run view: logs" if self._event_log.show_logs else "Run view: events")

    def action_show_artifacts(self) -> None:
        launch = self.live_run_controller.launch
        if launch is None:
            _notify(self, "No run artifacts yet.")
            return
        _notify(self, f"Artifacts: {launch.artifact_dir}")

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

    def action_clear_focus(self) -> None:
        self._focused_pane = "left"
        self._render_workbench()
        _notify(self, "Focus returned to navigation.")

    def action_focus_next(self) -> None:
        self._focused_pane = "right" if self._focused_pane == "left" else "left"
        self._render_workbench()

    def action_focus_previous(self) -> None:
        self.action_focus_next()

    def action_workspace_profiles(self) -> None:
        self._set_workspace("profiles")

    def action_workspace_loop(self) -> None:
        self._set_workspace("loop")

    def action_workspace_prompts(self) -> None:
        self._set_workspace("prompts")

    def action_workspace_run(self) -> None:
        self._set_workspace("run")

    def action_move_down(self) -> None:
        self._move_selection(1)

    def action_move_up(self) -> None:
        self._move_selection(-1)

    def action_select(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.expanded = not self._loop_diagram.expanded
            self._loop_diagram.rebuild()
            self._update_console_status()
            return
        if self._workspace == "profiles" and self._focused_pane == "left":
            selected = self._selected_profile_view()
            if selected is not None:
                self._select_profile(selected.name)
                _notify(self, f"Selected profile: {selected.name}")
        elif self._workspace == "run" and self._focused_pane == "left":
            self._selected_run_tab_index = (self._selected_run_tab_index + 1) % len(_RUN_TABS)
            _notify(self, f"Run view: {_RUN_TABS[self._selected_run_tab_index]}")
        else:
            self._focused_pane = "right"
        self._render_workbench()

    def action_save_loop(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            self.action_show_profile()
            return
        if not self._loop_diagram.is_dirty:
            _notify(self, "No unsaved loop changes.")
            return
        try:
            path = self._loop_diagram.model.save()
        except (OSError, RuntimeError, ValueError) as exc:
            _notify(self, f"Save failed: {exc}", severity="error")
            return
        self._refresh_profiles_from_disk()
        _notify(self, f"Saved loop to {path}")
        self._update_console_status()

    def action_toggle_phase(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.toggle_enabled()
            self._update_console_status()

    def action_cycle_harness(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.cycle_field("harness")
            self._update_console_status()

    def action_cycle_effort(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.cycle_field("effort")
            self._update_console_status()

    def action_edit_model(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._open_loop_text_field_prompt("model")

    def action_edit_timeout(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._open_loop_text_field_prompt("timeout")

    def action_edit_max_iterations(self) -> None:
        if self._workspace != "loop":
            self.action_import_profiles()
            return
        if self._loop_diagram is not None:
            self._open_loop_meta_prompt("max_iterations")

    def action_toggle_final_review(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.toggle_final_review()
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
        self._prompt_for_text(
            title="New profile",
            prompt="Profile name",
            initial="",
            on_submit=self._create_profile,
        )

    def action_clone_profile(self) -> None:
        source = self._profile_name()
        if source is None:
            _notify(self, "No profile is available to clone.")
            return
        self._prompt_for_text(
            title="Clone profile",
            prompt=f"Target name for clone of {source}",
            initial=f"{source}-copy",
            on_submit=lambda target: self._clone_profile(source, target),
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
        self._prompt_for_text(
            title="Import profiles",
            prompt="TOML profile file path",
            initial="",
            on_submit=self._import_profiles,
        )

    def _prompt_for_text(
        self,
        *,
        title: str,
        prompt: str,
        initial: str,
        on_submit: Any,
    ) -> None:
        screen_class = text_prompt_screen_class()
        push_screen = getattr(self, "push_screen", None)
        if screen_class is None or not callable(push_screen):
            _notify(self, f"{title} requires the interactive Textual prompt.")
            return

        def handle_result(value: str | None) -> None:
            if value is None:
                _notify(self, f"{title} cancelled.")
                return
            stripped = value.strip()
            if not stripped:
                _notify(self, f"{title} cancelled.")
                return
            on_submit(stripped)

        push_screen(
            screen_class(title=title, prompt=prompt, initial=initial),
            callback=handle_result,
        )

    def _open_loop_text_field_prompt(self, field: str) -> None:
        if self._loop_diagram is None:
            return

        def apply(value: str) -> None:
            self._loop_diagram.set_text_field(field, value)
            self._update_console_status()

        self._prompt_for_text(
            title=f"Edit {field}",
            prompt=f"{self._loop_diagram.current_phase()}.{field}",
            initial=self._loop_text_field_value(field),
            on_submit=apply,
        )

    def _open_loop_meta_prompt(self, field: str) -> None:
        if self._loop_diagram is None:
            return

        def apply(value: str) -> None:
            self._loop_diagram.set_loop_meta_field(field, value)
            self._update_console_status()

        self._prompt_for_text(
            title=f"Edit {field}",
            prompt=field.replace("_", " "),
            initial=self._loop_meta_field_value(field),
            on_submit=apply,
        )

    def _loop_text_field_value(self, field: str) -> str:
        if self._loop_diagram is None:
            return ""
        from code_review_loop import tui_loop_state

        phase = self._loop_diagram.current_phase()
        dotted = tui_loop_state.PHASE_DOTTED[phase].get(field)
        if dotted is None:
            return ""
        phase_config = getattr(self._loop_diagram.model.profile, phase, None)
        fallback = None
        if phase_config is not None:
            fallback = (
                getattr(phase_config, "message_model" if phase == "commit" else "model", None)
                if field == "model"
                else getattr(phase_config, "timeout_seconds", None)
            )
        value = self._loop_diagram.model.field_value(dotted, fallback)
        return "" if value is None else str(value)

    def _loop_meta_field_value(self, field: str) -> str:
        if self._loop_diagram is None:
            return ""
        from code_review_loop import tui_loop_state

        dotted = tui_loop_state.LOOP_META_DOTTED[field]
        profile = self._loop_diagram.model.profile
        fallback = (
            profile.pipeline.max_iterations
            if field == "max_iterations"
            else profile.runtime.inner_check_retries
        )
        value = self._loop_diagram.model.field_value(dotted, fallback)
        return "" if value is None else str(value)

    def _create_profile(self, profile_name: str) -> None:
        self._run_captured(
            tui_state.new_plan_for_name(profile_name),
            success=f"Created profile: {profile_name}",
        )

    def _clone_profile(self, source: str, target: str) -> None:
        self._run_captured(
            tui_state.clone_plan_for_name(source, target),
            success=f"Cloned profile: {source} -> {target}",
        )

    def _import_profiles(self, path: str) -> None:
        self._run_captured(tui_state.import_plan_for_path(path), success=f"Imported profiles: {path}")

    def _run_interactive(self, plan: tui_state.LaunchPlan, *, success: str) -> None:
        self._run_and_notify(plan, success=success, capture_output=False)

    def _run_captured(self, plan: tui_state.LaunchPlan, *, success: str) -> None:
        self._run_and_notify(plan, success=success, capture_output=True)

    def _run_and_notify(
        self, plan: tui_state.LaunchPlan, *, success: str, capture_output: bool
    ) -> None:
        result = self._run_plan(plan, capture_output=capture_output)
        if result.returncode == 0:
            if plan.mode in {"edit", "new", "clone", "delete", "import"}:
                self._refresh_profiles_from_disk()
            _notify(self, success)
            return
        _notify(self, f"{plan.mode} failed with exit {result.returncode}: {plan.profile_name}")

    def _refresh_profiles_from_disk(self) -> None:
        selected_profile_name = self._profile_name()
        cwd = Path(self.model.snapshot.cwd)

        try:
            refreshed_model = tui_state.build_shell_model(
                cwd=cwd,
                selected_profile_name=selected_profile_name,
            )
        except FileNotFoundError:
            try:
                refreshed_model = tui_state.build_shell_model(cwd=cwd)
            except ValueError as exc:
                _notify(
                    self,
                    "Profile refresh skipped: invalid profile config on disk; "
                    f"keeping current in-session profile state. ({exc})",
                )
                return
        except ValueError as exc:
            _notify(
                self,
                "Profile refresh skipped: invalid profile config on disk; "
                f"keeping current in-session profile state. ({exc})",
            )
            return

        try:
            refreshed_profiles_by_name = {
                profile.name: profile
                for profile in profiles.resolve_profiles(
                    cwd=cwd,
                    require_implemented=False,
                    include_builtins=True,
                )
            }
        except ValueError as exc:
            _notify(
                self,
                "Profile refresh skipped: invalid profile config on disk; "
                f"keeping current in-session profile state. ({exc})",
            )
            return

        self.model = refreshed_model
        self.profiles_by_name = refreshed_profiles_by_name
        if selected_profile_name is None or not self.model.snapshot.profiles:
            self._selected_profile_index = 0
        else:
            for index, profile in enumerate(self.model.snapshot.profiles):
                if profile.name == selected_profile_name:
                    self._selected_profile_index = index
                    break
            else:
                self._selected_profile_index = 0
        self._reload_loop_diagram()
        self._render_workbench()

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
        selected = self._selected_profile_view()
        return selected.name if selected is not None else None

    def _profile_by_name(self, profile_name: str | None) -> Any | None:
        if profile_name is None:
            return None
        profile = self.profiles_by_name.get(profile_name)
        if profile is not None:
            return profile
        try:
            return profiles.resolve_profile(
                profile_name,
                cwd=Path(self.model.snapshot.cwd),
                require_implemented=False,
            )
        except (OSError, ValueError):
            return None

    def _live_run_active(self) -> bool:
        process = self.live_run_controller.process
        return process is not None and process.poll() is None

    def _initial_profile_index(self) -> int:
        selected_name = self.model.selected_profile_name
        for index, profile in enumerate(self.model.snapshot.profiles):
            if profile.name == selected_name:
                return index
        return 0

    def _selected_profile_view(self) -> tui_state.ProfileView | None:
        if not self.model.snapshot.profiles:
            return None
        index = max(0, min(self._selected_profile_index, len(self.model.snapshot.profiles) - 1))
        self._selected_profile_index = index
        return self.model.snapshot.profiles[index]

    def _selected_phase_name(self) -> str:
        index = max(0, min(self._selected_phase_index, len(_PHASES) - 1))
        self._selected_phase_index = index
        return _PHASES[index]

    def _set_workspace(self, workspace: str) -> None:
        if workspace not in _WORKSPACES:
            return
        if workspace == "loop" and self._loop_diagram is not None:
            self._reload_loop_diagram()
        self._workspace = workspace
        self._focused_pane = "left"
        self._render_workbench()

    def _move_selection(self, delta: int) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.move(delta)
            self._update_console_status()
            return
        if self._workspace == "profiles" and self._focused_pane == "left":
            count = len(self.model.snapshot.profiles)
            if count:
                self._selected_profile_index = (self._selected_profile_index + delta) % count
        elif self._workspace in {"prompts", "run"} and self._focused_pane == "left":
            self._selected_phase_index = (self._selected_phase_index + delta) % len(_PHASES)
        elif self._workspace == "run" and self._focused_pane == "right":
            self._selected_run_tab_index = (self._selected_run_tab_index + delta) % len(_RUN_TABS)
        self._render_workbench()

    def _select_profile(self, profile_name: str) -> None:
        if (
            self._loop_diagram is not None
            and self._loop_diagram.is_dirty
            and self._loop_diagram.model.name != profile_name
        ):
            _notify(self, "Save or revert loop changes before loading another profile.")
            return
        for index, profile in enumerate(self.model.snapshot.profiles):
            if profile.name == profile_name:
                self._selected_profile_index = index
                selected_profile = self._profile_by_name(profile_name)
                self.model = replace(
                    self.model,
                    selected_profile_name=profile_name,
                    selected_launch_plan=(
                        tui_state.launch_plan(selected_profile, dry_run=True)
                        if selected_profile is not None
                        else None
                    ),
                )
                self._reload_loop_diagram()
                return

    def _render_workbench(self) -> None:
        _update_widget(self, "#status-bar", _status_bar_markup(self))
        _update_widget(self, "#screen-home", _left_pane_markup(self))
        _update_widget(self, "#screen-run-monitor", _right_pane_markup(self))
        _update_widget(self, "#footer-bar", _footer_markup(self))
        _set_widget_classes(self, "#screen-home", _pane_classes(self, "left"))
        _set_widget_classes(self, "#screen-run-monitor", _pane_classes(self, "right"))
        on_loop = self._workspace == "loop"
        on_run = self._workspace == "run"
        _set_widget_display(self, "#loop-pane", on_loop)
        _set_widget_display(self, "#run-pane", on_run)
        _set_widget_display(self, "#left-pane", not (on_loop or on_run))
        _set_widget_display(self, "#right-pane", not (on_loop or on_run))
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.rebuild()
        if self._workspace == "run":
            self._update_run_widgets()

    def _reload_loop_diagram(self) -> None:
        if self._loop_diagram is None:
            return
        if self._loop_diagram.is_dirty:
            return
        from code_review_loop import tui_loop_model

        profile_name = self._profile_name()
        if profile_name is None:
            return
        self._loop_diagram.model = tui_loop_model.LoopEditModel.load(
            profile_name, cwd=Path(self.model.snapshot.cwd)
        )
        self._loop_model = self._loop_diagram.model
        set_model = getattr(self._loop_diagram, "set_model", None)
        if callable(set_model):
            set_model(self._loop_model)
        else:
            self._loop_diagram.rebuild()

    def _refresh_live_run(self) -> None:
        if self._cancel_in_progress:
            return
        if self.live_run_controller.status == "idle":
            return
        if self.live_run_controller.status in tui_run_controller.TERMINAL_STATUSES:
            self._render_live_monitor()
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
        self._update_run_widgets()
        _update_widget(self, "#screen-run-monitor", _right_pane_markup(self))
        _update_widget(self, "#screen-home", _left_pane_markup(self))
        _set_widget_classes(self, "#screen-run-monitor", _pane_classes(self, "right"))
        _set_widget_classes(self, "#screen-home", _pane_classes(self, "left"))
        self._update_console_status()

    def _update_run_widgets(self) -> None:
        profile = self._profile_by_name(self._profile_name())
        if self._loop_run_view is not None:
            self._loop_run_view.set_state(self.live_run_controller, profile)
            self._loop_run_view.rebuild()
        if self._event_log is not None:
            self._event_log.set_controller(self.live_run_controller)
            self._event_log.rebuild()

    def _update_console_status(self) -> None:
        _update_widget(self, "#status-bar", _status_bar_markup(self))
        _update_widget(self, "#footer-bar", _footer_markup(self))
        _set_widget_classes(
            self,
            "#status-bar",
            _status_bar_classes(self.live_run_controller.status),
        )


class RevRemApp(_RevRemAppMixin, _TextualFallbackApp):
    """Import-safe app shell used by unit tests and by lazy Textual subclasses."""


def _screen_markup(screen: tui_state.TuiScreen) -> str:
    escaped_lines = "\n".join(tui_state.markup_escape(line) for line in screen.lines)
    return f"[b]{tui_state.markup_escape(screen.title)}[/b]\n{escaped_lines}"


def _screen_markup_for_app(app: Any, screen: tui_state.TuiScreen) -> str:
    if screen.name == "home":
        return _home_markup(app)
    if screen.name == "profiles":
        return _profiles_markup(app)
    if screen.name == "pipeline":
        return _pipeline_markup(app)
    return _screen_markup(screen)


def _panel_widget(markup: str, *, widget_id: str, focused: bool = False) -> Any:
    return _Static(markup, id=widget_id, classes=_panel_classes(focused), markup=True)


def _loop_diagram_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_model, tui_loop_widgets

    diagram_class = tui_loop_widgets.loop_diagram_class()
    if diagram_class is None:
        return None
    profile_name = app._profile_name()
    if profile_name is None:
        return None
    try:
        model = tui_loop_model.LoopEditModel.load(
            profile_name, cwd=Path(app.model.snapshot.cwd)
        )
    except (OSError, ValueError):
        return None
    app._loop_model = model
    widget = diagram_class(model)
    app._loop_diagram = widget
    return widget


def _loop_run_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    run_class = tui_loop_widgets.loop_run_view_class()
    if run_class is None:
        return None
    widget = run_class()
    app._loop_run_view = widget
    return widget


def _event_log_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    log_class = tui_loop_widgets.event_log_class()
    if log_class is None:
        return None
    widget = log_class()
    app._event_log = widget
    return widget


def _panel_classes(focused: bool) -> str:
    return "panel panel-focused" if focused else "panel panel-muted"


def _pane_classes(app: Any, pane: str) -> str:
    return _panel_classes(app._focused_pane == pane)


def _left_pane_markup(app: Any) -> str:
    if app._workspace == "profiles":
        return _profile_navigation_markup(app)
    title = {
        "loop": "Loop Phases",
        "prompts": "Prompt Sources",
        "run": "Run Timeline",
    }.get(app._workspace, "Navigation")
    return _phase_navigation_markup(app, title=title)


def _right_pane_markup(app: Any) -> str:
    if app._workspace == "profiles":
        return _profile_detail_markup(app)
    if app._workspace == "loop":
        return _loop_detail_markup(app)
    if app._workspace == "prompts":
        return _prompt_detail_markup(app)
    return _run_workspace_markup(app)


def _workspace_tabs_markup(app: Any) -> str:
    parts = []
    labels = (
        ("loop", "1 Loop"),
        ("run", "2 Run"),
        ("profiles", "3 Profiles"),
        ("prompts", "4 Prompts"),
    )
    for workspace, label in labels:
        escaped = tui_state.markup_escape(label)
        if app._workspace == workspace:
            parts.append(f"[workspace-active]{escaped}[/]")
        else:
            parts.append(f"[muted]{escaped}[/]")
    return "  ".join(parts)


def _profile_navigation_markup(app: Any) -> str:
    selected_name = app._profile_name()
    lines = [
        f"[b]Profiles[/b]  [muted]{len(app.model.snapshot.profiles)} available[/]",
        _workspace_tabs_markup(app),
        "",
    ]
    if not app.model.snapshot.profiles:
        lines.append("No profiles found. Press n to create one.")
        return "\n".join(lines)
    for index, profile in enumerate(app.model.snapshot.profiles):
        marker = ">" if index == app._selected_profile_index else " "
        selected = "[status-info]" if profile.name == selected_name else ""
        selected_end = "[/]" if selected else ""
        source = _short_source(profile.source)
        lines.append(
            f"{marker} {selected}{tui_state.markup_escape(profile.name)}{selected_end}  "
            f"[muted]{tui_state.markup_escape(source)}[/]"
        )
        lines.append(
            "  "
            f"base={tui_state.markup_escape(profile.base)} "
            f"max={profile.max_iterations} checks={len(profile.checks)}"
        )
    return "\n".join(lines)


def _profile_detail_markup(app: Any) -> str:
    profile_view = app._selected_profile_view()
    if profile_view is None:
        return "[b]Profile[/b]\nNo profile selected."
    profile = app._profile_by_name(profile_view.name)
    lines = [
        f"[b]Profile Detail[/b]  [muted]{tui_state.markup_escape(profile_view.name)}[/]",
        f"description: {tui_state.markup_escape(profile_view.description or '-')}",
        f"source: {tui_state.markup_escape(_short_source(profile_view.source))}",
        f"base: {tui_state.markup_escape(profile_view.base)}",
        f"max iterations: {profile_view.max_iterations}",
        f"checks: {len(profile_view.checks)}",
        "",
        "[b]Composed command[/b]",
        tui_state.markup_escape(_command_preview(app)),
        "",
        "[b]Actions[/b]",
        "d dry-run | r run | s show | e edit | n new | c clone | x export | i import",
    ]
    if profile is not None:
        lines.extend(("", "[b]Phase summary[/b]"))
        for phase in tui_state.pipeline_phases(profile):
            lines.append(_phase_summary_line(phase, selected=False))
    return "\n".join(lines)


def _phase_navigation_markup(app: Any, *, title: str) -> str:
    profile = app._profile_by_name(app._profile_name())
    lines = [
        f"[b]{tui_state.markup_escape(title)}[/]  [muted]{tui_state.markup_escape(app._profile_name() or '<none>')}[/]",
        _workspace_tabs_markup(app),
        "",
    ]
    if profile is None:
        lines.append("No selected profile.")
        return "\n".join(lines)
    phase_by_name = {phase.name: phase for phase in tui_state.pipeline_phases(profile)}
    for index, phase_name in enumerate(_PHASES):
        phase = phase_by_name.get(phase_name)
        marker = ">" if index == app._selected_phase_index else " "
        if phase is None:
            lines.append(f"{marker} [ ] {phase_name}")
        else:
            lines.append(f"{marker} {_phase_summary_line(phase, selected=index == app._selected_phase_index)}")
    if app._workspace == "run":
        lines.extend(("", "[b]Run tabs[/b]"))
        for index, tab in enumerate(_RUN_TABS):
            marker = ">" if index == app._selected_run_tab_index else " "
            lines.append(f"{marker} {tab}")
    return "\n".join(lines)


def _loop_detail_markup(app: Any) -> str:
    profile = app._profile_by_name(app._profile_name())
    if profile is None:
        return "[b]Loop[/b]\nNo selected profile."
    phase_name = app._selected_phase_name()
    lines = [
        f"[b]Loop Detail[/b]  [muted]{tui_state.markup_escape(phase_name)}[/]",
        f"profile: {tui_state.markup_escape(profile.name)}",
        "",
    ]
    for phase in tui_state.pipeline_phases(profile):
        if phase.name == phase_name:
            lines.extend(_phase_detail_lines(profile, phase))
            break
    else:
        lines.append("Phase metadata unavailable.")
    lines.extend(("", "[b]Loop shape[/b]"))
    lines.extend(_loop_shape_lines(profile))
    return "\n".join(lines)


def _prompt_detail_markup(app: Any) -> str:
    profile = app._profile_by_name(app._profile_name())
    if profile is None:
        return "[b]Prompts[/b]\nNo selected profile."
    phase_name = app._selected_phase_name()
    lines = [
        f"[b]Prompt Source[/b]  [muted]{tui_state.markup_escape(phase_name)}[/]",
        f"profile: {tui_state.markup_escape(profile.name)}",
        "",
    ]
    if phase_name == "triage":
        lines.append("field: triage.prompt")
        lines.append(f"editable: {_yes_no(profile.triage.prompt is not None)} via revrem config edit")
        lines.append(f"value: {tui_state.markup_escape(profile.triage.prompt or '<default triage contract prompt>')}")
    elif phase_name == "commit":
        lines.append("field: commit.message_prompt")
        lines.append(
            f"editable: {_yes_no(profile.commit.message_prompt is not None)} via revrem config edit"
        )
        lines.append(
            "value: "
            + tui_state.markup_escape(profile.commit.message_prompt or "<default commit-message prompt>")
        )
    elif phase_name == "review":
        lines.append("source: native codex review prompt or composed external review prompt")
        lines.append("editable: no dedicated profile field; edit harness/model/profile settings")
    elif phase_name == "remediation":
        fragment_names = sorted(
            {
                fragment
                for rule in profile.triage.routing.rule
                for fragment in rule.then.prompt_fragments
            }
        )
        lines.append("source: generated remediation prompt plus route prompt fragments")
        lines.append("editable: route fragments are configured in triage.routing.rule[].then.prompt_fragments")
        lines.append("fragments: " + (", ".join(fragment_names) if fragment_names else "none configured"))
    else:
        lines.append("source: verification check commands and failed-check handoff")
        lines.append("editable: pipeline.checks in the owning profile config")
        for command in profile.pipeline.checks[:8]:
            lines.append(f"- {tui_state.markup_escape(command)}")
        if len(profile.pipeline.checks) > 8:
            lines.append(f"... {len(profile.pipeline.checks) - 8} more")
    lines.extend(("", "Press e to open the owning profile config."))
    return "\n".join(lines)


def _run_workspace_markup(app: Any) -> str:
    lines = _live_monitor_markup(app.live_run_controller).splitlines()
    tab = _RUN_TABS[app._selected_run_tab_index]
    lines.insert(1, f"view: {tab}")
    if tab == "stdout":
        lines.extend(_bounded_lines("stdout", app.live_run_controller.stdout_lines()))
    elif tab == "stderr":
        lines.extend(_bounded_lines("stderr", app.live_run_controller.stderr_lines()))
    elif tab == "summary":
        lines.extend(_summary_lines(app.live_run_controller))
    return "\n".join(lines)


def _footer_markup(app: Any) -> str:
    live = _live_hint(app)
    if app._help_visible:
        keys = _help_markup(visible=True).replace("\n", " | ")
    elif app._workspace == "profiles":
        keys = "[j/down]move [up]move [Enter]select [d]dry-run [r]run [?]help"
    elif app._workspace == "loop":
        phase = (
            app._loop_diagram.current_phase()
            if getattr(app, "_loop_diagram", None) is not None
            else "review"
        )
        route_keys = " [Enter]routes" if phase == "triage" else ""
        keys = (
            "[up/down]phase [Enter]expand [space]toggle [m]harness [f]effort "
            "[M]model [t]timeout [i]iterations [F]final [s]save [r]run"
            f"{route_keys} [?]help"
        )
    elif app._workspace == "prompts":
        keys = "[j/down]source [up]source [e]edit config [Tab]focus [?]help"
    else:
        keys = "[k]stop [l]logs/events [o]artifacts [r]run [?]help"
    return f"{tui_state.markup_escape(live)}\n{tui_state.markup_escape(keys)}"


def _live_hint(app: Any) -> str:
    if app._cancel_in_progress:
        return "live: cancelling child process"
    if app._quit_confirmation_pending:
        return "live: press q again to cancel and quit"
    if app._pending_live_confirmation_profile:
        return f"live: press r again to start {app._pending_live_confirmation_profile}"
    if app._live_run_active():
        return "live: running; press k to cancel"
    return f"live: {app.live_run_controller.status}"


def _command_preview(app: Any) -> str:
    profile = app._profile_by_name(app._profile_name())
    if profile is None:
        return "revrem config new final-pr"
    return tui_state.launch_plan(profile, dry_run=False).shell_command


def _phase_summary_line(phase: tui_state.PhaseView, *, selected: bool) -> str:
    marker = _phase_marker(phase)
    state = "on" if phase.enabled else "off"
    details = [state]
    if phase.harness:
        details.append(phase.harness)
    if phase.model:
        details.append(_truncate(phase.model, 24))
    effort = harnesses.phase_effort_text(phase.harness, phase.reasoning_effort)
    if effort:
        details.append(f"effort={effort}")
    if phase.command_count is not None:
        details.append(f"commands={phase.command_count}")
    text = f"{marker} {phase.name}: " + ", ".join(tui_state.markup_escape(item) for item in details)
    if selected:
        return f"[status-info]{text}[/]"
    if not phase.enabled:
        return f"[muted]{text}[/]"
    return text


def _phase_marker(phase: tui_state.PhaseView) -> str:
    if not phase.enabled:
        return "[ ]"
    return "[[ok]]"


def _phase_detail_lines(profile: profiles.Profile, phase: tui_state.PhaseView) -> list[str]:
    lines = [
        f"state: {'enabled' if phase.enabled else 'disabled'}",
        f"harness: {phase.harness or '-'}",
        f"model: {phase.model or '-'}",
        f"reasoning effort: {harnesses.phase_effort_text(phase.harness, phase.reasoning_effort) or '-'}",
        f"timeout: {_timeout_text(phase.timeout_seconds)}",
    ]
    if phase.name == "checks":
        lines.append(f"commands: {len(profile.pipeline.checks)}")
        for command in profile.pipeline.checks[:8]:
            lines.append(f"- {tui_state.markup_escape(command)}")
    if phase.name == "triage" and profile.triage.routing.enabled:
        lines.append(f"routing: default={profile.triage.routing.default_route}")
        lines.append(f"routes: {len(profile.triage.routes)}")
    return lines


def _loop_shape_lines(profile: profiles.Profile) -> list[str]:
    lines = [
        "review",
        "  -> triage" if profile.triage.enabled else "  -> triage skipped",
        "  -> remediation",
        f"  -> checks ({len(profile.pipeline.checks)})",
    ]
    if profile.commit.enabled:
        lines.append("  -> commit after passing checks")
    else:
        lines.append("  -> commit off")
    lines.append("  -> final review" if profile.pipeline.final_review else "  -> final review off")
    return lines


def _timeout_text(value: float | None) -> str:
    if value is None:
        return "default"
    if value == 0:
        return "none"
    return f"{value:g}s"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _bounded_lines(label: str, lines: Sequence[str], *, limit: int = 12) -> list[str]:
    if not lines:
        return ["", f"[b]{label}[/]", "No captured lines yet."]
    return ["", f"[b]{label}[/]", *[tui_state.markup_escape(line) for line in lines[-limit:]]]


def _summary_lines(controller: tui_run_controller.LiveRunController) -> list[str]:
    if controller.launch is None:
        return ["", "[b]summary[/]", "No live run has been launched."]
    summary_path = controller.launch.artifact_dir / "summary.json"
    if not summary_path.is_file():
        return ["", "[b]summary[/]", f"waiting for {tui_state.markup_escape(str(summary_path))}"]
    return ["", "[b]summary[/]", tui_state.markup_escape(str(summary_path))]


def _home_markup(app: Any) -> str:
    snapshot = app.model.snapshot
    implemented = [harness.name for harness in snapshot.harnesses if harness.implemented]
    reserved_count = sum(1 for harness in snapshot.harnesses if not harness.implemented)
    harness_text = ", ".join(implemented[:5]) or "none"
    if len(implemented) > 5:
        harness_text += f", +{len(implemented) - 5}"
    if reserved_count:
        harness_text += f" ({reserved_count} reserved)"
    artifact_count = sum(len(run.artifacts) for run in snapshot.run_monitors)
    lines = [
        "[b]Home[/b]",
        f"Workspace: {tui_state.markup_escape(snapshot.cwd)}",
        f"Profile: {tui_state.markup_escape(app.model.selected_profile_name or 'none')}",
        (
            f"Profiles {len(snapshot.profiles)} | Recent runs {len(snapshot.recent_runs)} "
            f"| Artifact links {artifact_count}"
        ),
        f"Harnesses: {tui_state.markup_escape(harness_text)}",
    ]
    if app.model.selected_launch_plan is not None:
        lines.append(
            f"Dry-run: {tui_state.markup_escape(app.model.selected_launch_plan.shell_command)}"
        )
    return "\n".join(lines)


def _profiles_markup(app: Any) -> str:
    selected = app.model.selected_profile_name
    profiles_by_name = {profile.name: profile for profile in app.model.snapshot.profiles}
    ordered = []
    if selected and selected in profiles_by_name:
        ordered.append(profiles_by_name[selected])
    ordered.extend(profile for profile in app.model.snapshot.profiles if profile.name != selected)
    lines = ["[b]Profiles[/b]"]
    for index, profile in enumerate(ordered[:7]):
        marker = ">" if profile.name == selected else " "
        description = _truncate(profile.description or "-", 44)
        source = _short_source(profile.source)
        lines.append(
            f"{marker} {tui_state.markup_escape(profile.name)}  "
            f"base={tui_state.markup_escape(profile.base)}  "
            f"max={profile.max_iterations}  checks={len(profile.checks)}  "
            f"{tui_state.markup_escape(source)}"
        )
        if description != "-":
            lines.append(f"  {tui_state.markup_escape(description)}")
        if index == 0 and profile.name == selected:
            lines.append("  selected: d dry-run | r run | s show | e edit | x export")
    remaining = len(ordered) - 7
    if remaining > 0:
        lines.append(f"... {remaining} more profiles")
    return "\n".join(lines)


def _pipeline_markup(app: Any) -> str:
    profile = app._profile_by_name(app.model.selected_profile_name)
    if profile is None:
        return "[b]Pipeline[/b]\nNo selected profile."
    lines = [
        "[b]Pipeline[/b]",
        f"Profile: {tui_state.markup_escape(profile.name)}",
    ]
    for phase in tui_state.pipeline_phases(profile):
        state = "on" if phase.enabled else "off"
        details = [state]
        if phase.harness:
            details.append(phase.harness)
        if phase.model:
            details.append(_truncate(phase.model, 26))
        effort = harnesses.phase_effort_text(phase.harness, phase.reasoning_effort)
        if effort:
            details.append(f"effort={effort}")
        if phase.command_count is not None:
            details.append(f"commands={phase.command_count}")
        lines.append(f"{phase.name}: " + ", ".join(tui_state.markup_escape(item) for item in details))
    if profile.triage.routing.enabled:
        route_count = len(profile.triage.routes)
        route = profile.triage.routing.default_route or "none"
        lines.append(f"routing: default={tui_state.markup_escape(route)} routes={route_count}")
    if app.model.selected_launch_plan is not None:
        lines.append(
            f"Dry-run: {tui_state.markup_escape(app.model.selected_launch_plan.shell_command)}"
        )
    return "\n".join(lines)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _short_source(source: str | None) -> str:
    if not source:
        return "-"
    if source == "builtin":
        return "builtin"
    path = Path(source)
    if path.name == ".revrem.toml":
        return "project"
    if path.name == "profiles.toml":
        return "user"
    return path.name or source


def _screen_by_name(model: tui_state.TuiShellModel, name: str) -> tui_state.TuiScreen | None:
    for screen in model.screens:
        if screen.name == name:
            return screen
    return None


def _controls_markup(app: Any) -> str:
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
        "\\[d]ry-run  \\[r]un  \\[k]cancel  \\[l]logs/events  \\[o]artifacts  \\[h]help  \\[q]quit\n\n"
        "[b]Profile actions[/b]\n"
        "\\[s]how  \\[e]dit  \\[n]ew...  \\[c]lone...  e\\[x]port  \\[i]mport..."
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
        for event in tui_state.event_views_from_events(snapshot.events[-8:]):
            lines.append(f"  {tui_state.markup_escape(tui_state.event_row_text(event))}")
    return "\n".join(lines)


def _status_bar_markup(app: Any) -> str:
    profile_name = app._profile_name() or "<none>"
    dirty = (
        "*"
        if getattr(app, "_loop_diagram", None) is not None and app._loop_diagram.is_dirty
        else ""
    )
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
    help_hint = "? hide help" if app._help_visible else "? help"
    return (
        f"RevRem  {tui_state.markup_escape(Path(app.model.snapshot.cwd).name or app.model.snapshot.cwd)}"
        f"  profile={tui_state.markup_escape(profile_name)}{dirty}"
        f"  workspace={tui_state.markup_escape(app._workspace)}"
        f"  focus={tui_state.markup_escape(app._focused_pane)}\n"
        f"command: {tui_state.markup_escape(_command_preview(app))}\n"
        f"live={tui_state.markup_escape(status)}{tui_state.markup_escape(pending)}"
        f"  1 loop 2 run 3 profiles 4 prompts  {help_hint}  q quit"
    )


def _status_bar_classes(status: tui_run_controller.RunControllerStatus) -> str:
    return f"status-{status}"


def _help_markup(*, visible: bool) -> str:
    if not visible:
        return "[b]Help[/b]\nPress \\[h] for full keybindings."
    return (
        "[b]Help[/b]\n"
        "Universal: \\[q] quit | \\[Tab] next focus | \\[Shift+Tab] previous focus | \\[Esc] clear focus | \\[h] hide help\n"
        "Loop: \\[space] toggle phase | \\[m] harness | \\[f] effort | \\[M] model | \\[t] timeout | \\[i] iterations | \\[F] final review | \\[s] save\n"
        "Run: \\[d] dry-run selected profile | \\[r] confirm/start live run | \\[k] cancel active run\n"
        "Profile: \\[s] show | \\[e] edit | \\[n] new... | \\[c] clone... | \\[x] export | \\[i] import profiles | \\[delete] delete\n"
        "Prompts: Enter submits text; Esc cancels and returns to global keys."
    )


def _resolve_widget(app: Any, selector: str) -> Any | None:
    query_one = getattr(app, "query_one", None)
    if not callable(query_one):
        return None
    try:
        return query_one(selector)
    except Exception:
        return None


def _update_widget(app: Any, selector: str, value: str) -> None:
    widget = _resolve_widget(app, selector)
    update = getattr(widget, "update", None)
    if callable(update):
        update(value)


def _set_widget_classes(app: Any, selector: str, classes: str) -> None:
    widget = _resolve_widget(app, selector)
    set_classes = getattr(widget, "set_classes", None)
    if callable(set_classes):
        set_classes(classes)


def _set_widget_display(app: Any, selector: str, visible: bool) -> None:
    widget = _resolve_widget(app, selector)
    if widget is not None:
        widget.display = visible


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


def _notify(app: Any, message: str, *, severity: str = "information") -> None:
    notify = getattr(app, "notify", None)
    if callable(notify):
        try:
            notify(message, severity=severity)
        except TypeError:
            notify(message)
    else:
        print(message)
