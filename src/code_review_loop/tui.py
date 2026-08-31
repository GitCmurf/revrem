"""Optional Textual TUI entry point for RevRem."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast

from code_review_loop import (
    check_presets,
    harnesses,
    profiles,
    tui_loop_state,
    tui_profiles_state,
    tui_prompt_assets,
    tui_run_controller,
    tui_session,
    tui_state,
)

INSTALL_HINT = "Install it with: python -m pip install 'revrem[tui]'"
_TEXTUAL_IMPORT_ERROR: Exception | None = None
_TEXTUAL_COMPONENTS: _TextualComponents | None = None
_TEXTUAL_APP_CLASS: type[Any] | None = None
_TEXT_PROMPT_SCREEN_CLASS: type[Any] | None = None
_HELP_SCREEN_CLASS: type[Any] | None = None
_CHECK_PICKER_SCREEN_CLASS: type[Any] | None = None
_WORKSPACES = ("loop", "run", "profiles", "prompts")
_PHASES = ("review", "triage", "remediation", "checks", "commit")
_RUN_TABS = ("events", "stdout", "stderr", "summary")
_FOCUS_PANES = ("left", "right")
_PROMPT_FIELD_BY_PHASE = {"triage": "triage.prompt", "commit": "commit.message_prompt"}
_ROUTE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


@dataclass(frozen=True)
class TuiBootstrapResult:
    """Complete workbench state installed as one UI-thread transaction."""

    model: tui_state.TuiShellModel
    profiles_by_name: dict[str, profiles.Profile]
    loop_model: Any | None
    loop_session: tui_session.LoopSession


@dataclass(frozen=True)
class _CheckChoice:
    key: str
    label: str
    checks: tuple[str, ...] | None
    group: str


_Binding: Any | None = None
_Header: Any = object
_Footer: Any = object
_Static: Any = object
_Horizontal: Any | None = None
_Vertical: Any | None = None
_VerticalScroll: Any | None = None
_Input: Any | None = None
_Button: Any | None = None
_Select: Any | None = None
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
        run_textual_app(
            selected_profile_name=args.profile,
            skip_splash=args.skip_splash,
        )
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
    parser.add_argument(
        "--skip-splash",
        action="store_true",
        help="Start directly in the TUI without the brief splash screen.",
    )
    return parser.parse_args(argv)


def run_textual_app(
    *, selected_profile_name: str | None = None, skip_splash: bool = False
) -> None:
    app_class = textual_app_class()
    cwd = Path.cwd()
    if selected_profile_name is not None:
        profiles.resolve_profile(
            selected_profile_name,
            cwd=cwd,
            require_implemented=False,
        )
    app_class(
        model=tui_state.bootstrap_shell_model(cwd),
        profiles_by_name={},
        skip_splash=skip_splash,
        bootstrap_request=(cwd, selected_profile_name),
    ).run()


def _build_tui_bootstrap(
    cwd: Path, selected_profile_name: str | None
) -> TuiBootstrapResult:
    resolved_profiles = tuple(
        profiles.resolve_profiles(
            cwd=cwd,
            require_implemented=False,
            include_builtins=True,
        )
    )
    model = tui_state.build_shell_model(
        cwd=cwd,
        selected_profile_name=selected_profile_name,
        resolved_profiles=resolved_profiles,
    )
    profiles_by_name = {profile.name: profile for profile in resolved_profiles}
    loop_model: Any | None = None
    loop_session = tui_session.LoopSession(profile_name=model.selected_profile_name)

    # An explicit --profile is authoritative. Last-run replay is the default
    # only when the operator did not make an explicit startup selection.
    seeded = _last_run_loop_model(cwd) if selected_profile_name is None else None
    if seeded is not None:
        loop_model, origin, pending = seeded
        selected = profiles_by_name.get(loop_model.name)
        if selected is not None:
            model = replace(
                model,
                selected_profile_name=loop_model.name,
                selected_launch_plan=tui_state.launch_plan(selected, dry_run=True),
            )
            loop_session = tui_session.LoopSession(
                profile_name=loop_model.name,
                origin_label=origin,
                pending_review=pending,
            )
        else:
            loop_model = None

    if loop_model is None and model.selected_profile_name is not None:
        from code_review_loop import tui_loop_model

        loop_model = tui_loop_model.LoopEditModel.load(
            model.selected_profile_name, cwd=cwd
        )

    return TuiBootstrapResult(
        model=model,
        profiles_by_name=profiles_by_name,
        loop_model=loop_model,
        loop_session=loop_session,
    )


def _textual_unavailable_message() -> str:
    message = (
        f"ERROR: revrem ui requires the optional Textual dependency. {INSTALL_HINT}"
    )
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
    global _Input, _Button, _Select, _ModalScreen, _TabbedContent, _TabPane
    _Binding = getattr(components.binding, "Binding", None)
    _Header = components.widgets.Header
    _Footer = components.widgets.Footer
    _Static = components.widgets.Static
    _Horizontal = getattr(components.containers, "Horizontal", None)
    _Vertical = getattr(components.containers, "Vertical", None)
    _VerticalScroll = getattr(components.containers, "VerticalScroll", None)
    _Input = getattr(components.widgets, "Input", None)
    _Button = getattr(components.widgets, "Button", None)
    _Select = getattr(components.widgets, "Select", None)
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
                _binding(
                    "escape", "cancel", "Cancel", priority=True, binding_cls=_Binding
                )
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


def help_screen_class() -> type[Any] | None:
    global _HELP_SCREEN_CLASS
    components = _load_textual_components()
    if components is None:
        return None
    _install_textual_components(components)
    if _ModalScreen is None or _Vertical is None or _Static is object:
        return None
    if _HELP_SCREEN_CLASS is None:
        modal_screen: Any = _ModalScreen
        vertical: Any = _Vertical
        static: Any = _Static

        class HelpScreen(modal_screen):
            BINDINGS = [
                _binding("escape", "cancel", "Close", priority=True),
                _binding("?", "cancel", "Close", priority=True),
                _binding("h", "cancel", "Close", priority=True),
            ]

            def __init__(self, content: str) -> None:
                super().__init__()
                self.content = content

            def compose(self):
                with vertical(id="help-dialog"):
                    yield static(self.content, id="help-content", markup=False)
                    yield static("Esc, ? or h closes help", markup=False)

            def action_cancel(self) -> None:
                self.dismiss(None)

        _HELP_SCREEN_CLASS = HelpScreen
    return _HELP_SCREEN_CLASS


def check_picker_screen_class() -> type[Any] | None:
    global _CHECK_PICKER_SCREEN_CLASS
    components = _load_textual_components()
    if components is None:
        return None
    _install_textual_components(components)
    if _ModalScreen is None or _Vertical is None or _Static is object:
        return None
    if _CHECK_PICKER_SCREEN_CLASS is None:
        modal_screen: Any = _ModalScreen
        vertical: Any = _Vertical
        static: Any = _Static

        class CheckPickerScreen(modal_screen):
            BINDINGS = [
                _binding("up", "move_up", "Up", priority=True),
                _binding("k", "move_up", "Up", priority=True),
                _binding("down", "move_down", "Down", priority=True),
                _binding("j", "move_down", "Down", priority=True),
                _binding("enter", "select", "Select", priority=True),
                _binding("escape", "cancel", "Cancel", priority=True),
            ]

            def __init__(self, choices: tuple[_CheckChoice, ...]) -> None:
                super().__init__()
                self.choices = choices
                self.selected_index = 0
                self._body: Any | None = None

            def compose(self):
                with vertical(id="check-picker-dialog"):
                    self._body = static("", id="check-picker-content", markup=False)
                    yield self._body
                    yield static(
                        "Up/Down choose · Enter apply · Esc cancel", markup=False
                    )

            def on_mount(self) -> None:
                self._rebuild()

            def action_move_up(self) -> None:
                self._move(-1)

            def action_move_down(self) -> None:
                self._move(1)

            def action_select(self) -> None:
                if self.choices:
                    self.dismiss(self.choices[self.selected_index].key)

            def action_cancel(self) -> None:
                self.dismiss(None)

            def _move(self, delta: int) -> None:
                if self.choices:
                    self.selected_index = (self.selected_index + delta) % len(
                        self.choices
                    )
                    self._rebuild()

            def _rebuild(self) -> None:
                if self._body is not None:
                    self._body.update(
                        _check_picker_text(self.choices, self.selected_index)
                    )

        _CHECK_PICKER_SCREEN_CLASS = CheckPickerScreen
    return _CHECK_PICKER_SCREEN_CLASS


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
        ("left", "workspace_previous", "Previous workspace"),
        ("right", "workspace_next", "Next workspace"),
        ("j", "move_down", "Down"),
        ("down", "move_down", "Down"),
        ("up", "move_up", "Up"),
        ("enter", "select", "Select"),
        _binding(
            "space",
            "toggle_phase",
            "Toggle phase",
            priority=True,
            binding_cls=binding_cls,
        ),
        _binding(
            "m", "cycle_harness", "Harness", priority=True, binding_cls=binding_cls
        ),
        _binding("f", "cycle_effort", "Effort", priority=True, binding_cls=binding_cls),
        _binding("M", "edit_model", "Model", priority=True, binding_cls=binding_cls),
        _binding(
            "t", "edit_timeout", "Timeout", priority=True, binding_cls=binding_cls
        ),
        _binding(
            "i",
            "edit_max_iterations",
            "Max iterations",
            priority=True,
            binding_cls=binding_cls,
        ),
        _binding("b", "edit_base", "Base", priority=True, binding_cls=binding_cls),
        _binding(
            "I",
            "edit_inner_retries",
            "Inner retries",
            priority=True,
            binding_cls=binding_cls,
        ),
        _binding(
            "F",
            "toggle_final_review",
            "Final review",
            priority=True,
            binding_cls=binding_cls,
        ),
        ("d", "launch_dry_run", "Dry run"),
        ("r", "launch_run", "Run"),
        ("R", "prepare_review_retry", "Retry review"),
        ("k", "cancel_run", "Cancel run"),
        _binding(
            "l", "toggle_logs", "Detail view", priority=True, binding_cls=binding_cls
        ),
        ("o", "show_artifacts", "Artifacts"),
        ("u", "toggle_pending_review", "Reuse review"),
        ("v", "show_pending_review", "Review details"),
        _binding(
            "p",
            "choose_checks",
            "Choose checks",
            priority=True,
            binding_cls=binding_cls,
        ),
        ("tab", "focus_next", "Focus next"),
        ("shift+tab", "focus_previous", "Focus previous"),
        _binding(
            "escape",
            "clear_focus",
            "Clear focus",
            priority=True,
            binding_cls=binding_cls,
        ),
        ("s", "save_loop", "Save"),
        ("e", "edit_context", "Edit"),
        ("g", "goto_prompts", "Prompts"),
        ("a", "add_route", "Add route"),
        ("n", "new_profile", "New"),
        ("c", "context_continue", "Continue"),
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

    #splash-pane {
        height: 1fr;
        content-align: center middle;
        background: $background;
        color: $success;
    }

    #loop-pane {
        display: none;
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    #run-pane {
        display: none;
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    #profiles-pane, #prompts-pane {
        display: none;
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    .loop-diagram {
        width: 1fr;
        height: auto;
        background: $background;
    }

    .loop-run {
        width: 1fr;
        height: auto;
    }

    .loop-row {
        height: auto;
        background: $panel;
        margin-bottom: 1;
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
        padding: 0 1;
        background: $surface;
    }

    .run-phase {
        width: 1fr;
        height: auto;
    }

    .event-log {
        margin-top: 1;
        height: 1fr;
        min-height: 6;
        overflow-y: auto;
    }

    .event-log:focus {
        border-left: thick $accent;
    }

    .profile-picker, .prompt-library {
        width: 1fr;
        height: auto;
    }

    .triage-routes-table {
        margin-left: 4;
        height: auto;
        padding: 0 1;
        background: $boost;
        color: $text;
    }

    .loop-returns {
        margin-top: 1;
        padding: 0 1;
        height: auto;
        background: $panel;
        color: $text;
    }

    #loop-command-panel {
        margin-top: 1;
        padding: 0 1;
        height: auto;
        border: round $accent;
        background: $surface;
        color: $text;
    }

    #loop-settings-panel {
        margin-top: 1;
        padding: 0 1;
        height: auto;
        border: round $surface;
        background: $panel;
        color: $text;
    }

    HelpScreen, CheckPickerScreen {
        align: center middle;
    }

    #help-dialog, #check-picker-dialog {
        width: 90%;
        max-width: 110;
        height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }

    #help-content, #check-picker-content {
        height: auto;
    }

    #status-bar {
        dock: top;
        height: 2;
        padding: 0 2;
        text-style: bold;
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
        height: 1;
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

    .status-completed-findings, .status-completed-unknown, .status-budget {
        color: $warning;
    }

    .status-failed, .status-setup-failed, .status-failed-forced-cleanup,
    .status-interrupted-before-run-initialized {
        color: $error;
    }

    TextPrompt {
        align: center middle;
    }

    RouteEditModal {
        align: center middle;
    }

    #prompt-dialog, #route-edit-dialog {
        width: 64;
        height: auto;
        max-width: 90%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    #prompt-title, #route-edit-title {
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
        skip_splash: bool = False,
        bootstrap_request: tuple[Path, str | None] | None = None,
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
        self._loop_diagram: Any | None = None
        self._loop_model: Any | None = None
        self.loop_session = tui_session.LoopSession(
            profile_name=model.selected_profile_name
        )
        self._loop_run_view: Any | None = None
        self._event_log: Any | None = None
        self._profile_picker: Any | None = None
        self._prompt_library: Any | None = None
        self._prompt_target_key: str | None = None
        self._prompt_return_workspace: str | None = None
        self._live_run_profile: profiles.Profile | None = None
        self._splash_visible = not skip_splash
        self._bootstrap_request = bootstrap_request
        self._bootstrap_loading = bootstrap_request is not None
        self._bootstrap_slow = False
        self._bootstrap_error: str | None = None
        self._bootstrap_started_at = time.monotonic()
        if bootstrap_request is None and model.selected_profile_name is not None:
            from code_review_loop import tui_loop_model

            try:
                self._loop_model = tui_loop_model.LoopEditModel.load(
                    model.selected_profile_name, cwd=Path(model.snapshot.cwd)
                )
            except (OSError, ValueError):
                self._loop_model = None

    def compose(self):
        yield _Header(show_clock=True)
        if _Horizontal is not None and _Vertical is not None:
            yield _Static(
                _startup_markup(self),
                id="splash-pane",
                markup=False,
            )
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
                        yield _Static(
                            _loop_command_markup(self),
                            id="loop-command-panel",
                            markup=True,
                        )
                        yield _Static(
                            _loop_settings_markup(self),
                            id="loop-settings-panel",
                            markup=False,
                        )
                        yield loop_widget
                run_widget = _loop_run_widget(self)
                event_log = _event_log_widget(self)
                if run_widget is not None and event_log is not None:
                    with _Vertical(id="run-pane"):
                        yield run_widget
                        yield event_log
                profile_picker = _profile_picker_widget(self)
                if profile_picker is not None:
                    with _Vertical(id="profiles-pane"):
                        yield profile_picker
                prompt_library = _prompt_library_widget(self)
                if prompt_library is not None:
                    with _Vertical(id="prompts-pane"):
                        yield prompt_library
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
        set_timer = getattr(self, "set_timer", None)
        if callable(set_timer) and self._splash_visible and not self._bootstrap_loading:
            set_timer(0.7, self._dismiss_splash)
        if self._bootstrap_loading:
            self._start_bootstrap()
            if callable(set_timer):
                set_timer(10.0, self._mark_bootstrap_slow)
        self._render_workbench()

    def on_key(self, event: Any) -> None:
        if self._splash_visible:
            self._dismiss_splash()
            if self._bootstrap_loading:
                stop = getattr(event, "stop", None)
                if callable(stop):
                    stop()
                return
        elif self._bootstrap_loading:
            return
        if getattr(event, "key", None) not in {"?", "question_mark", "h"}:
            return
        stop = getattr(event, "stop", None)
        if callable(stop):
            stop()
        self.action_toggle_help()

    def _dismiss_splash(self) -> None:
        if not self._splash_visible:
            return
        self._splash_visible = False
        self._render_workbench()

    def _start_bootstrap(self) -> None:
        request = self._bootstrap_request
        if request is None:
            return
        cwd, selected_profile_name = request

        def load() -> None:
            try:
                result = _build_tui_bootstrap(cwd, selected_profile_name)
            except (OSError, RuntimeError, ValueError) as exc:
                _call_from_thread(
                    self, lambda exc=exc: self._finish_bootstrap_error(exc)
                )
                return
            _call_from_thread(
                self,
                lambda: self._finish_bootstrap(result),
            )

        _run_background(self, load)

    def _finish_bootstrap(
        self,
        result: TuiBootstrapResult,
    ) -> None:
        self.model = result.model
        self.profiles_by_name = result.profiles_by_name
        self._loop_model = result.loop_model
        self.loop_session = result.loop_session
        self._selected_profile_index = self._initial_profile_index()
        self._bootstrap_loading = False
        self._bootstrap_request = None
        elapsed = time.monotonic() - self._bootstrap_started_at
        delay = max(0.0, 0.5 - elapsed) if self._splash_visible else 0.0
        set_timer = getattr(self, "set_timer", None)
        if delay and callable(set_timer):
            set_timer(delay, self._complete_bootstrap_view)
            return
        self._complete_bootstrap_view()

    def _finish_bootstrap_error(self, exc: Exception) -> None:
        self._bootstrap_loading = False
        self._bootstrap_error = str(exc)
        _update_widget(self, "#splash-pane", _startup_markup(self))
        self._render_workbench()

    def _complete_bootstrap_view(self) -> None:
        self._splash_visible = False
        refresh = getattr(self, "refresh", None)
        if callable(refresh):
            refresh(recompose=True)
        call_after_refresh = getattr(self, "call_after_refresh", None)
        if callable(call_after_refresh):
            call_after_refresh(self._finish_recomposed_workbench)
            return
        self._finish_recomposed_workbench()

    def _finish_recomposed_workbench(self) -> None:
        """Render and focus only after replacement widgets are mounted."""
        self._render_workbench()
        if self._workspace == "loop" and self._loop_diagram is not None:
            set_focus = getattr(self, "set_focus", None)
            if callable(set_focus):
                set_focus(self._loop_diagram)

    def _mark_bootstrap_slow(self) -> None:
        if not self._bootstrap_loading:
            return
        self._bootstrap_slow = True
        _update_widget(self, "#splash-pane", _startup_markup(self))

    def action_launch_dry_run(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to dry-run.")
            return
        selected = self._profile_by_name(profile_name)
        if selected is None:
            _notify(self, "No profile is available to dry-run.")
            return
        if not self._pending_review_is_launchable():
            return
        if self._workspace == "profiles":
            plan = tui_state.launch_plan(selected, dry_run=True)
            result = run_launch_plan(plan, cwd=Path(self.model.snapshot.cwd))
        else:
            try:
                effective = (
                    self._loop_diagram.model.effective_profile()
                    if self._workspace == "loop" and self._loop_diagram is not None
                    else selected
                )
                with tempfile.TemporaryDirectory(prefix="revrem-tui-") as temp_dir:
                    snapshot = Path(temp_dir) / "profile.toml"
                    snapshot.write_text(
                        profiles.profile_to_toml(effective, include_wrapper=True),
                        encoding="utf-8",
                    )
                    plan = self.loop_session.compile_launch_plan(
                        effective, dry_run=True, profile_snapshot=snapshot
                    )
                    result = run_launch_plan(plan, cwd=Path(self.model.snapshot.cwd))
            except (OSError, RuntimeError, ValueError) as exc:
                _notify(
                    self,
                    f"Dry run could not build its launch plan: {exc}",
                    severity="error",
                )
                return
        if result.returncode == 0:
            _notify(self, f"Dry run completed: {profile_name}")
            return
        _notify(self, f"Dry run failed with exit {result.returncode}: {profile_name}")

    def action_launch_run(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to run.")
            return
        selected = self._profile_by_name(profile_name)
        if selected is None:
            _notify(self, "No profile is available to run.")
            return
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
            _notify(
                self, f"Press r again to start an experimental live run: {profile_name}"
            )
            self._update_console_status()
            return
        self._pending_live_confirmation_profile = None
        if not self._pending_review_is_launchable():
            return
        effective = (
            self._loop_diagram.model.effective_profile()
            if self._workspace == "loop" and self._loop_diagram is not None
            else selected
        )
        plan = self._profile_launch_plan(effective, dry_run=False)
        self._live_run_profile = effective
        try:
            launch = self.live_run_controller.start(
                profile=effective,
                plan=plan,
                cwd=Path(self.model.snapshot.cwd),
                entrypoint_resolver=current_entrypoint_argv,
                snapshot_profile=self._workspace == "loop",
            )
        except OSError:
            self._live_run_profile = None
            _notify(
                self,
                self.live_run_controller.message or f"Live run failed: {profile_name}",
            )
            self._render_live_monitor()
            return
        self._workspace = "run"
        self._focused_pane = "right"
        _notify(self, f"Live run started: {profile_name} ({launch.artifact_dir_arg})")
        self._render_workbench()

    def action_toggle_pending_review(self) -> None:
        if self._workspace != "loop" or self.loop_session.pending_review is None:
            _notify(self, "No pending review is available for this loop.")
            return
        self.loop_session = self.loop_session.toggle_pending_review()
        selected = self.loop_session.pending_review
        if selected is not None and selected.selected and not selected.compatible:
            message = "Older review will be validated before remediation."
        elif selected is not None and selected.selected:
            message = "Compatible review will be reused."
        else:
            message = "The next run will start with a fresh review."
        _notify(
            self,
            message,
        )
        self._render_workbench()

    def action_show_pending_review(self) -> None:
        if self._workspace == "run":
            summary = self.live_run_controller.read_summary()
            if not isinstance(summary, dict):
                _notify(self, "No completed run diagnostics are available.")
                return
            details = [
                f"Outcome: {summary.get('stopped_reason', 'unknown')}",
                str(
                    summary.get("latest_review_excerpt")
                    or "No review excerpt recorded."
                ),
            ]
            for key in ("bug_report_path", "latest_review_path"):
                if summary.get(key):
                    details.append(f"{key.replace('_', ' ')}: {summary[key]}")
            screen_class = help_screen_class()
            if screen_class is not None:
                push_screen = getattr(self, "push_screen", None)
                if callable(push_screen):
                    push_screen(screen_class("\n\n".join(details)))
            return
        pending = self.loop_session.pending_review
        if self._workspace != "loop" or pending is None:
            _notify(self, "No pending review is available for this loop.")
            return
        excerpt = pending.excerpt.strip().replace("\n", " ")
        detail = f"Pending review: {pending.path}"
        if excerpt:
            detail += f" · {_truncate(excerpt, 500)}"
        _notify(self, detail)

    def _pending_review_is_launchable(self) -> bool:
        if self._workspace == "profiles":
            return True
        pending = self.loop_session.pending_review
        if pending is None or not pending.selected:
            return True
        if not pending.path.is_file():
            self.loop_session = replace(self.loop_session, pending_review=None)
            _notify(
                self,
                f"Review input disappeared; the next run is now fresh: {pending.path}",
                severity="error",
            )
            self._render_workbench()
            return False
        previous = pending.git_state
        if (
            pending.compatible
            and isinstance(previous, dict)
            and previous.get("available") is True
        ):
            from code_review_loop.cli.config_support import current_git_state_for_latest

            base = previous.get("base")
            current = current_git_state_for_latest(
                Path(self.model.snapshot.cwd),
                base if isinstance(base, str) and base else "main",
            )
            if (
                current is not None
                and current.get("available") is True
                and any(
                    previous.get(key) != current.get(key)
                    for key in ("head", "base", "base_commit", "merge_base")
                )
            ):
                self.loop_session = replace(
                    self.loop_session,
                    pending_review=replace(
                        pending,
                        compatible=False,
                        selected=False,
                    ),
                )
                _notify(
                    self,
                    "Git state changed. The review is now available for explicit "
                    "validation; press u to select it.",
                    severity="error",
                )
                self._render_workbench()
                return False
        return True

    def _profile_launch_plan(
        self, profile: profiles.Profile, *, dry_run: bool
    ) -> tui_state.LaunchPlan:
        if self._workspace == "profiles":
            return tui_state.launch_plan(profile, dry_run=dry_run)
        return self.loop_session.compile_launch_plan(profile, dry_run=dry_run)

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
        current = getattr(self._event_log, "mode", "timeline")
        self._event_log.mode = "timeline" if current == "logs" else "logs"
        self._event_log.rebuild()
        _notify(self, f"Run detail: {self._event_log.mode}")

    def action_prepare_review_retry(self) -> None:
        if self._workspace != "run":
            return
        summary = self.live_run_controller.read_summary()
        if (
            not isinstance(summary, dict)
            or summary.get("stopped_reason") != "review_unknown"
        ):
            _notify(self, "This run does not need an inconclusive-review retry.")
            return
        self._prepare_terminal_followup(summary, reuse_review=False)
        _notify(self, "Fresh review prepared from the run's effective configuration.")

    def action_context_continue(self) -> None:
        if self._workspace == "profiles":
            self.action_clone_profile()
            return
        if self._workspace != "run":
            return
        summary = self.live_run_controller.read_summary()
        launch = self.live_run_controller.launch
        if not isinstance(summary, dict) or launch is None:
            _notify(self, "No completed run summary is available.")
            return
        from code_review_loop import resume

        issues = resume.resume_precondition_issues(
            launch.artifact_dir, cwd=Path(self.model.snapshot.cwd)
        )
        blocking = [issue.message for issue in issues if issue.severity == "blocking"]
        if blocking:
            _notify(
                self, "Continuation blocked: " + "; ".join(blocking), severity="error"
            )
            return
        self._prepare_terminal_followup(summary, reuse_review=True)
        _notify(self, "Continuation prepared from the latest actionable review.")

    def _prepare_terminal_followup(
        self, summary: dict[str, object], *, reuse_review: bool
    ) -> None:
        from code_review_loop import resume, tui_loop_model

        profile = self._live_run_profile
        launch = self.live_run_controller.launch
        if profile is None or launch is None:
            raise RuntimeError("completed run configuration is unavailable")
        model = tui_loop_model.LoopEditModel(
            name=profile.name, profile=profile, cwd=Path(self.model.snapshot.cwd)
        )
        model.mark_replay_baseline()
        self._loop_model = model
        if self._loop_diagram is not None:
            self._loop_diagram.set_model(model)
        pending = None
        if reuse_review:
            review_path = resume.latest_resume_review_path(
                summary, run_dir=launch.artifact_dir
            )
            if review_path is not None:
                raw_git_state = summary.get("git_state")
                pending = tui_session.PendingReviewSelection(
                    path=review_path,
                    run_dir=launch.artifact_dir,
                    final_status=str(summary.get("final_status") or "") or None,
                    stopped_reason=str(summary.get("stopped_reason") or "") or None,
                    excerpt=str(summary.get("latest_review_excerpt") or ""),
                    compatible=True,
                    selected=True,
                    git_state=(
                        raw_git_state if isinstance(raw_git_state, dict) else None
                    ),
                )
        self.loop_session = tui_session.LoopSession(
            profile_name=profile.name,
            origin_label=f"prepared from run {launch.artifact_dir.name}",
            pending_review=pending,
        )
        self._workspace = "loop"
        self._focused_pane = "left"
        self._render_workbench()

    def action_show_artifacts(self) -> None:
        if self._workspace != "run":
            return
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
        screen_class = help_screen_class()
        push_screen = getattr(self, "push_screen", None)
        if screen_class is None or not callable(push_screen):
            _notify(self, _help_text(self))
            return
        active_screen = getattr(self, "screen", None)
        if isinstance(active_screen, screen_class):
            active_screen.dismiss(None)
            return
        if _ModalScreen is not None and isinstance(active_screen, _ModalScreen):
            return
        push_screen(screen_class(_help_text(self)))

    def action_clear_focus(self) -> None:
        if _cancel_active_modal(self):
            return
        if (
            self._workspace == "loop"
            and self._loop_diagram is not None
            and self._loop_diagram.route_mode
        ):
            self._loop_diagram.exit_route_mode()
            self._update_console_status()
            return
        self._focused_pane = "left"
        self._render_workbench()
        _notify(self, "Focus returned to navigation.")

    def action_focus_next(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            if (
                self._loop_diagram.current_phase() == "triage"
                and self._loop_diagram.expanded_phase == "triage"
                and self._loop_diagram.route_names()
            ):
                if self._loop_diagram.route_mode:
                    self._loop_diagram.exit_route_mode()
                    _notify(self, "Loop focus: phases.")
                else:
                    self._loop_diagram.enter_route_mode()
                    _notify(self, "Loop focus: triage routes.")
                self._update_console_status()
                return
            _notify(self, "Loop focus has no secondary target here.")
            return
        if self._workspace == "run":
            if self._event_log is not None:
                modes = ("timeline", "events", "logs", "summary")
                current = getattr(self._event_log, "mode", "timeline")
                self._event_log.mode = modes[(modes.index(current) + 1) % len(modes)]
                self._event_log.rebuild()
                _notify(self, f"Run detail: {self._event_log.mode}")
            return
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

    def action_workspace_previous(self) -> None:
        self._cycle_workspace(-1)

    def action_workspace_next(self) -> None:
        self._cycle_workspace(1)

    def _cycle_workspace(self, delta: int) -> None:
        if _ModalScreen is not None and isinstance(
            getattr(self, "screen", None), _ModalScreen
        ):
            return
        index = _WORKSPACES.index(self._workspace)
        self._set_workspace(_WORKSPACES[(index + delta) % len(_WORKSPACES)])

    def action_move_down(self) -> None:
        if self._workspace == "run" and self._event_log is not None:
            scroll = getattr(self._event_log, "scroll_down", None)
            if callable(scroll):
                scroll(animate=False)
            return
        self._move_selection(1)

    def action_move_up(self) -> None:
        if self._workspace == "run" and self._event_log is not None:
            scroll = getattr(self._event_log, "scroll_up", None)
            if callable(scroll):
                scroll(animate=False)
            return
        self._move_selection(-1)

    def action_select(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            if self._loop_diagram.route_mode:
                route = self._loop_diagram.selected_route()
                if route is not None:
                    self._open_route_edit_modal(route)
                return
            if (
                self._loop_diagram.current_phase() == "triage"
                and self._loop_diagram.expanded_phase == "triage"
            ):
                route = self._loop_diagram.selected_route()
                if route is not None:
                    self._open_route_edit_modal(route)
                    return
                if self._loop_diagram.enter_route_mode():
                    self._update_console_status()
                    return
            if (
                self._loop_diagram.current_phase() == "triage"
                and self._loop_diagram.expanded_phase != "triage"
                and self._loop_diagram.route_names()
            ):
                self._loop_diagram.expanded_phase = "triage"
                self._loop_diagram.rebuild()
                self._update_console_status()
                return
            phase = self._loop_diagram.current_phase()
            self._loop_diagram.expanded_phase = (
                None if self._loop_diagram.expanded_phase == phase else phase
            )
            self._loop_diagram.rebuild()
            self._update_console_status()
            return
        if self._workspace == "profiles" and self._profile_picker is not None:
            selected_name = self._profile_picker.selected_name()
            if selected_name is not None:
                self._load_profile_into_loop(selected_name)
            return
        if self._workspace == "prompts" and self._prompt_library is not None:
            self._apply_selected_prompt_asset()
            return
        if self._workspace == "profiles" and self._focused_pane == "left":
            selected = self._selected_profile_view()
            if selected is not None:
                self._select_profile(selected.name)
                _notify(self, f"Selected profile: {selected.name}")
        elif self._workspace == "run" and self._focused_pane == "left":
            self._selected_run_tab_index = (self._selected_run_tab_index + 1) % len(
                _RUN_TABS
            )
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

    def action_edit_base(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._open_loop_meta_prompt("base")

    def action_edit_inner_retries(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            return
        if self._loop_diagram.current_phase() != "checks":
            _notify(self, "Check-failure retries: focus the Checks phase first.")
            return
        self._open_loop_meta_prompt("inner_check_retries")

    def action_choose_checks(self) -> None:
        if (
            self._workspace != "loop"
            or self._loop_diagram is None
            or self._loop_diagram.current_phase() != "checks"
        ):
            _notify(self, "Choose checks: focus the Checks phase first.")
            return
        current = self._current_check_commands()
        detected = check_presets.detect_check_presets(Path(self.model.snapshot.cwd))
        recent = check_presets.recent_check_presets(
            Path(self.model.snapshot.cwd),
            excluded=tuple(item.checks for item in detected),
        )
        choices: list[_CheckChoice] = []
        if current:
            choices.append(
                _CheckChoice(
                    "current", "Keep current configured checks", current, "Current"
                )
            )
        choices.extend(
            _CheckChoice(item.key, item.label, item.checks, "Recommended")
            for item in detected
        )
        choices.extend(
            _CheckChoice(item.key, item.label, item.checks, "Recent runs")
            for item in recent
            if item.checks != current
        )
        choices.extend(
            (
                _CheckChoice("custom", "Enter custom commands", None, "Other"),
                _CheckChoice("builtin-only", "Built-in cleanliness only", (), "Other"),
            )
        )
        screen_class = check_picker_screen_class()
        push_screen = getattr(self, "push_screen", None)
        if screen_class is None or not callable(push_screen):
            _notify(self, "Check selection requires the interactive Textual picker.")
            return

        by_key = {choice.key: choice for choice in choices}

        def handle_result(key: str | None) -> None:
            if key is None or key == "current":
                return
            if key == "custom":
                self._open_checks_prompt()
                return
            choice = by_key.get(key)
            if choice is not None and choice.checks is not None:
                self._apply_check_commands(choice.checks)

        push_screen(screen_class(tuple(choices)), callback=handle_result)

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
            tui_state.show_plan_for_name(profile_name),
            success=f"Shown profile: {profile_name}",
        )

    def action_edit_context(self) -> None:
        if self._workspace == "loop":
            if (
                self._loop_diagram is not None
                and self._loop_diagram.current_phase() == "checks"
            ):
                self._open_checks_prompt()
                return
            self._open_prompt_field_prompt()
            return
        self.action_edit_profile()

    def action_edit_profile(self) -> None:
        profile_name = self._profile_name()
        if profile_name is None:
            _notify(self, "No profile is available to edit.")
            return
        self._run_interactive(
            tui_state.edit_plan_for_name(profile_name),
            success=f"Edited profile: {profile_name}",
        )

    def action_goto_prompts(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            self._set_workspace("prompts")
            return
        phase = self._loop_diagram.current_phase()
        key = _PROMPT_FIELD_BY_PHASE.get(phase)
        if key is None:
            _notify(self, f"{phase} has no scalar prompt field.")
            return
        self._prompt_target_key = key
        self._prompt_return_workspace = "loop"
        self._set_workspace("prompts")
        _notify(self, f"Select a prompt asset for {key}, then press Enter.")

    def action_add_route(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            _notify(self, "Add route: open the Loop workspace and focus triage first.")
            return
        if self._loop_diagram.current_phase() != "triage":
            _notify(self, "Add route: focus triage first.")
            return
        self._prompt_for_text(
            title="Add route",
            prompt="New route name",
            initial="",
            on_submit=self._apply_route_add,
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
        diagram = self._loop_diagram

        def apply(value: str) -> None:
            diagram.set_text_field(field, value)
            self._update_console_status()

        prompt = f"{diagram.current_phase()}.{field}"
        if field == "model":
            from code_review_loop import model_catalog

            fields = tui_loop_state.PHASE_DOTTED[diagram.current_phase()]
            harness_dotted = fields.get("harness")
            harness = (
                str(diagram.model.field_value(harness_dotted, "codex"))
                if harness_dotted
                else "codex"
            )
            models = model_catalog.load_catalog(
                Path(self.model.snapshot.cwd)
            ).models_for(harness)
            if models:
                prompt += "\nCatalog options: " + ", ".join(item.id for item in models)
        self._prompt_for_text(
            title=f"Edit {field}",
            prompt=prompt,
            initial=self._loop_text_field_value(field),
            on_submit=apply,
        )

    def _open_loop_meta_prompt(self, field: str) -> None:
        if self._loop_diagram is None:
            return
        diagram = self._loop_diagram

        def apply(value: str) -> None:
            diagram.set_loop_meta_field(field, value)
            self._update_console_status()

        self._prompt_for_text(
            title=f"Edit {field}",
            prompt=field.replace("_", " "),
            initial=self._loop_meta_field_value(field),
            on_submit=apply,
        )

    def _open_checks_prompt(self) -> None:
        if self._loop_diagram is None:
            return
        diagram = self._loop_diagram
        initial = "; ".join(self._current_check_commands())

        def apply(value: str) -> None:
            diagram.model.set_field("pipeline.checks", value)
            diagram.rebuild()
            self._update_console_status()
            _notify(self, "Updated checks (unsaved; press s to save).")

        self._prompt_for_text(
            title="Edit checks",
            prompt="Verification commands (; or newline separated)",
            initial=initial,
            on_submit=apply,
        )

    def _current_check_commands(self) -> tuple[str, ...]:
        if self._loop_diagram is None:
            return ()
        current = self._loop_diagram.model.field_value(
            "pipeline.checks", self._loop_diagram.model.profile.pipeline.checks
        )
        if not isinstance(current, list | tuple):
            return ()
        return tuple(str(item) for item in current if isinstance(item, str))

    def _apply_check_commands(self, checks: tuple[str, ...]) -> None:
        if self._loop_diagram is None:
            return
        self._loop_diagram.model.set_field("pipeline.checks", list(checks))
        self._loop_diagram.rebuild()
        self._update_console_status()
        label = (
            f"Selected {len(checks)} configured checks"
            if checks
            else "Selected built-in cleanliness only"
        )
        _notify(self, f"{label} (unsaved; press s to save).")

    def _open_prompt_field_prompt(self) -> None:
        if self._loop_diagram is None:
            return
        phase = self._loop_diagram.current_phase()
        key = _PROMPT_FIELD_BY_PHASE.get(phase)
        if key is None:
            _notify(self, f"{phase} has no editable scalar prompt field.")
            return
        current = self._loop_diagram.model.field_value(key, "")
        self._prompt_for_text(
            title=f"Edit {key}",
            prompt="Prompt text",
            initial=current if isinstance(current, str) else "",
            on_submit=lambda value: self._apply_prompt_edit(key, value),
        )

    def _apply_prompt_edit(self, key: str, value: str) -> None:
        if self._loop_diagram is None:
            return
        self._loop_diagram.model.set_field(key, value)
        self._loop_diagram.rebuild()
        self._update_console_status()
        _notify(self, f"Set {key} (unsaved; press s to save).")

    def _apply_selected_prompt_asset(self) -> None:
        if self._prompt_library is None:
            return
        asset = self._prompt_library.selected_asset()
        if asset is None:
            _notify(self, "No prompt asset selected.")
            return
        if self._prompt_target_key is None:
            _notify(self, f"Prompt asset: {asset.name}")
            return
        key = self._prompt_target_key
        if asset.kind == "contract" and key != "triage.prompt":
            _notify(
                self,
                f"Prompt contract {asset.name} can only target triage.prompt.",
                severity="error",
            )
            return
        if asset.kind == "contract":
            diagram = self._loop_diagram
            if diagram is None:
                return
            # Contract assets control triage contract version directly. Their
            # full prompt text must not be injected into triage.prompt to
            # avoid duplicate additive guidance at runtime.
            contract = asset.name.removeprefix("triage_")
            if contract not in profiles.TRIAGE_CONTRACT_CHOICES:
                _notify(
                    self,
                    f"Unsupported triage contract prompt asset: {asset.name}.",
                    severity="error",
                )
                return
            diagram.model.set_field("triage.contract", contract)
            self._prompt_target_key = None
            diagram.rebuild()
            self._update_console_status()
            _notify(self, "Set triage.contract from prompt contract asset.")
            self._set_workspace(self._prompt_return_workspace or "loop")
            self._prompt_return_workspace = None
            return
        try:
            text = tui_prompt_assets.prompt_asset_text(
                asset, cwd=Path(self.model.snapshot.cwd)
            )
        except ValueError as exc:
            _notify(self, f"Prompt apply failed: {exc}", severity="error")
            return
        self._prompt_target_key = None
        self._apply_prompt_edit(key, text)
        self._set_workspace(self._prompt_return_workspace or "loop")
        self._prompt_return_workspace = None

    def _open_route_edit_modal(self, route: str) -> None:
        from code_review_loop import tui_loop_widgets

        if self._loop_diagram is None:
            return
        modal_class = tui_loop_widgets.route_edit_modal_class()
        push_screen = getattr(self, "push_screen", None)
        if modal_class is None or not callable(push_screen):
            _notify(self, "Route editing requires the interactive Textual modal.")
            return
        values = self._route_values(route)

        def handle_result(result: object) -> None:
            if result is None:
                _notify(self, "Route edit cancelled.")
                return
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[1], dict)
            ):
                route_name, values = result
                self._apply_route_row_edit(str(route_name), values)
                return
            _notify(self, "Route edit returned an unexpected result.", severity="error")

        route_names = (
            self._loop_diagram.route_names()
            if hasattr(self._loop_diagram, "route_names")
            else tuple(sorted(self._loop_diagram.model.profile.triage.routes))
        )
        push_screen(
            modal_class(route=route, values=values, route_names=route_names),
            callback=handle_result,
        )

    def _route_values(self, route: str) -> dict[str, str]:
        if self._loop_diagram is None:
            return {}
        profile = self._loop_diagram.model.profile
        route_config = profile.triage.routes.get(route)
        values: dict[str, str] = {}
        for cell in profiles.ROUTE_KEYS:
            fallback = getattr(route_config, cell, None) if route_config else None
            value = self._loop_diagram.model.field_value(
                f"triage.routes.{route}.{cell}", fallback
            )
            values[cell] = "" if value is None else str(value)
        return values

    def _apply_route_edit(self, route: str, cell: str, value: str) -> None:
        if self._loop_diagram is None:
            return
        value = value.strip()
        error = self._route_edit_error(route, {cell: value})
        if error is not None:
            _notify(self, error, severity="error")
            return
        self._loop_diagram.model.set_field(f"triage.routes.{route}.{cell}", value)
        self._loop_diagram.rebuild()
        self._update_console_status()
        _notify(self, f"Set triage.routes.{route}.{cell} (unsaved; press s to save).")

    def _apply_route_row_edit(self, route: str, values: dict[str, object]) -> None:
        if self._loop_diagram is None:
            return
        current = self._route_values(route)
        changes: dict[str, object] = {}
        clearable_route_fields = {
            "model",
            "reasoning_effort",
            "timeout_seconds",
            "fallback",
        }
        for cell in profiles.ROUTE_KEYS:
            value = str(values.get(cell, "")).strip()
            if value == "":
                if cell not in clearable_route_fields or current.get(cell, "") == "":
                    continue
                changes[cell] = None
                continue
            if value == current.get(cell, ""):
                continue
            changes[cell] = value
        if not changes:
            _notify(self, f"No changes for route {route}.")
            return
        error = self._route_edit_error(route, changes)
        if error is not None:
            _notify(self, error, severity="error")
            return
        for changed_cell in changes:
            changed_value = changes[changed_cell]
            self._loop_diagram.model.set_field(
                f"triage.routes.{route}.{changed_cell}", changed_value
            )
        self._loop_diagram.rebuild()
        self._update_console_status()
        _notify(self, f"Updated route {route} (unsaved; press s to save).")

    def _route_edit_error(self, route: str, changes: dict[str, object]) -> str | None:
        if self._loop_diagram is None:
            return None
        route_names = set(self._loop_diagram.route_names())
        route_names.add(route)
        for cell, value in changes.items():
            string_value = None if value is None else str(value)
            field = f"triage.routes.{route}.{cell}"
            if cell not in profiles.ROUTE_KEYS:
                return f"Unknown route cell: {cell}"
            if cell == "harness":
                try:
                    if string_value is None:
                        return f"{field} must be a harness name"
                    profiles.validate_harness_name(string_value, field=field)
                except ValueError as exc:
                    return str(exc)
            elif cell == "timeout_seconds":
                if string_value is None or string_value == "":
                    continue
                try:
                    timeout_seconds = float(string_value)
                except ValueError:
                    return f"{field} must be a number"
                if timeout_seconds < 0:
                    return f"{field} must be 0 or greater"
            elif cell == "sandbox":
                if string_value not in profiles.EXEC_SANDBOX_CHOICES:
                    return (
                        f"{field} must be one of "
                        f"{', '.join(profiles.EXEC_SANDBOX_CHOICES)}"
                    )
            elif (
                cell == "fallback" and string_value and string_value not in route_names
            ):
                return f"{field} refers to unknown route: {string_value}"
        fallback_value = changes.get("fallback")
        fallback = None if fallback_value is None else str(fallback_value)
        return self._route_fallback_error(route, fallback)

    def _route_fallback_error(self, route: str, fallback: str | None) -> str | None:
        if self._loop_diagram is None or fallback is None or fallback == "":
            return None
        route_names = self._loop_diagram.route_names()
        fallbacks: dict[str, str] = {}
        for route_name in route_names:
            route_config = self._loop_diagram.model.profile.triage.routes.get(
                route_name
            )
            current_fallback = route_config.fallback if route_config else None
            value = self._loop_diagram.model.field_value(
                f"triage.routes.{route_name}.fallback", current_fallback
            )
            fallbacks[route_name] = "" if value is None else str(value)
        fallbacks[route] = fallback
        chain = [route]
        current = route
        while fallbacks.get(current):
            next_route = fallbacks[current]
            if next_route in chain:
                return (
                    f"triage.routes.{route}.fallback creates a fallback cycle: "
                    f"{' -> '.join((*chain, next_route))}"
                )
            chain.append(next_route)
            current = next_route
        return None

    def _apply_route_add(self, route: str) -> None:
        if self._loop_diagram is None:
            return
        route = route.strip()
        if _ROUTE_NAME_RE.fullmatch(route) is None:
            _notify(
                self,
                "Invalid route name: use letters, numbers, '-' or '_'.",
                severity="error",
            )
            return
        if route in self._loop_diagram.model.profile.triage.routes:
            _notify(self, f"Route already exists: {route}", severity="error")
            return
        if (
            self._loop_diagram.model.field_value(f"triage.routes.{route}.harness", None)
            is not None
        ):
            _notify(self, f"Route already exists: {route}", severity="error")
            return
        self._loop_diagram.model.set_field(f"triage.routes.{route}.harness", "codex")
        self._loop_diagram.model.set_field(
            f"triage.routes.{route}.sandbox", "workspace-write"
        )
        if not self._loop_diagram.model.profile.triage.routing.enabled:
            self._loop_diagram.model.set_field("triage.contract", "v2")
            self._loop_diagram.model.set_field("triage.enabled", "true")
            self._loop_diagram.model.set_field("triage.routing.enabled", "true")
            self._loop_diagram.model.set_field("triage.routing.default_route", route)
        self._loop_diagram.route_mode = True
        route_names = self._loop_diagram.route_names()
        if route in route_names:
            self._loop_diagram.selected_route_index = route_names.index(route)
        self._loop_diagram.rebuild()
        self._update_console_status()
        _notify(self, f"Added route {route} (unsaved; press s to save).")

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
                getattr(
                    phase_config,
                    "message_model" if phase == "commit" else "model",
                    None,
                )
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
        fallback = {
            "base": profile.pipeline.base,
            "max_iterations": profile.pipeline.max_iterations,
            "inner_check_retries": profile.runtime.inner_check_retries,
        }[field]
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
        self._run_captured(
            tui_state.import_plan_for_path(path), success=f"Imported profiles: {path}"
        )

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
        _notify(
            self,
            f"{plan.mode} failed with exit {result.returncode}: {plan.profile_name}",
        )

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

    def _load_profile_into_loop(self, name: str) -> None:
        from code_review_loop import tui_loop_model

        if (
            self._loop_diagram is not None
            and getattr(
                self._loop_diagram.model,
                "is_user_modified",
                self._loop_diagram.is_dirty,
            )
            and self._loop_diagram.model.name != name
        ):
            _notify(self, "Save or revert loop changes before loading another profile.")
            return
        try:
            model = tui_loop_model.LoopEditModel.load(
                name, cwd=Path(self.model.snapshot.cwd)
            )
        except (OSError, ValueError) as exc:
            _notify(self, f"Load failed: {exc}", severity="error")
            return
        self._loop_model = model
        if self._loop_diagram is not None:
            set_model = getattr(self._loop_diagram, "set_model", None)
            if callable(set_model):
                set_model(model)
            else:
                self._loop_diagram.model = model
                self._loop_diagram.rebuild()
        selected_profile = self._profile_by_name(name)
        for index, profile_view in enumerate(self.model.snapshot.profiles):
            if profile_view.name == name:
                self._selected_profile_index = index
                break
        self.model = replace(
            self.model,
            selected_profile_name=name,
            selected_launch_plan=(
                tui_state.launch_plan(selected_profile, dry_run=True)
                if selected_profile is not None
                else None
            ),
        )
        self.loop_session = tui_session.LoopSession(profile_name=name)
        self._workspace = "loop"
        self._focused_pane = "left"
        self._render_workbench()
        if model.profile.source == profiles.BUILTIN_PROFILE_SOURCE:
            _notify(
                self,
                f"Loaded preset '{name}' read-only; press c to clone before editing.",
            )
        else:
            _notify(self, f"Loaded {name} into the loop.")

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
        return run_launch_plan(
            plan, cwd=Path(self.model.snapshot.cwd), capture_output=capture_output
        )

    def _profile_name(self) -> str | None:
        if self._workspace == "profiles" and self._profile_picker is not None:
            selected_name = cast(str | None, self._profile_picker.selected_name())
            if selected_name is not None:
                return selected_name
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
        index = max(
            0, min(self._selected_profile_index, len(self.model.snapshot.profiles) - 1)
        )
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
        if workspace != "prompts":
            self._prompt_target_key = None
            self._prompt_return_workspace = None
        self._workspace = workspace
        self._focused_pane = "left"
        self._render_workbench()

    def _move_selection(self, delta: int) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.move(delta)
            self._update_console_status()
            return
        if self._workspace == "profiles" and self._profile_picker is not None:
            self._profile_picker.move(delta)
            return
        if self._workspace == "prompts" and self._prompt_library is not None:
            self._prompt_library.move(delta)
            return
        if self._workspace == "profiles" and self._focused_pane == "left":
            count = len(self.model.snapshot.profiles)
            if count:
                self._selected_profile_index = (
                    self._selected_profile_index + delta
                ) % count
        elif self._workspace in {"prompts", "run"} and self._focused_pane == "left":
            self._selected_phase_index = (self._selected_phase_index + delta) % len(
                _PHASES
            )
        elif self._workspace == "run" and self._focused_pane == "right":
            self._selected_run_tab_index = (self._selected_run_tab_index + delta) % len(
                _RUN_TABS
            )
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
                self.loop_session = tui_session.LoopSession(profile_name=profile_name)
                self._reload_loop_diagram()
                return

    def _render_workbench(self) -> None:
        _update_widget(self, "#status-bar", _status_bar_markup(self))
        _update_widget(self, "#screen-home", _left_pane_markup(self))
        _update_widget(self, "#screen-run-monitor", _right_pane_markup(self))
        _update_widget(self, "#footer-bar", _footer_markup(self))
        _update_widget(self, "#loop-command-panel", _loop_command_markup(self))
        _update_widget(self, "#loop-settings-panel", _loop_settings_markup(self))
        _set_widget_classes(self, "#screen-home", _pane_classes(self, "left"))
        _set_widget_classes(self, "#screen-run-monitor", _pane_classes(self, "right"))
        on_loop = self._workspace == "loop"
        on_run = self._workspace == "run"
        on_profiles = self._workspace == "profiles"
        on_prompts = self._workspace == "prompts"
        startup = bool(
            getattr(self, "_splash_visible", False)
            or getattr(self, "_bootstrap_loading", False)
            or getattr(self, "_bootstrap_error", None)
        )
        _update_widget(self, "#splash-pane", _startup_markup(self))
        _set_widget_display(self, "#splash-pane", startup)
        _set_widget_display(self, "#loop-pane", on_loop and not startup)
        _set_widget_display(self, "#run-pane", on_run and not startup)
        _set_widget_display(self, "#profiles-pane", on_profiles and not startup)
        _set_widget_display(self, "#prompts-pane", on_prompts and not startup)
        _set_widget_display(
            self,
            "#left-pane",
            not startup and not (on_loop or on_run or on_profiles or on_prompts),
        )
        _set_widget_display(
            self,
            "#right-pane",
            not startup and not (on_loop or on_run or on_profiles or on_prompts),
        )
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.rebuild()
        if self._workspace == "run":
            self._update_run_widgets()
        if on_profiles and self._profile_picker is not None:
            self._profile_picker.set_rows(
                tui_profiles_state.profile_picker_groups(self.model.snapshot)
            )
            self._profile_picker.rebuild()
        if on_prompts and self._prompt_library is not None:
            self._prompt_library.rebuild()

    def _reload_loop_diagram(self) -> None:
        if self._loop_diagram is None:
            return
        if self._loop_diagram.is_dirty:
            return
        from code_review_loop import tui_loop_model

        profile_name = self._profile_name()
        if profile_name is None:
            return
        try:
            self._loop_diagram.model = tui_loop_model.LoopEditModel.load(
                profile_name, cwd=Path(self.model.snapshot.cwd)
            )
        except (OSError, ValueError) as exc:
            _notify(
                self,
                "Profile reload skipped: invalid profile config on disk; "
                f"keeping current in-session profile state. ({exc})",
            )
            return
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
            status: str | None = None
            error: Exception | None = None
            try:
                status = self.live_run_controller.cancel()
            except Exception as exc:
                error = exc

            def finish_update() -> None:
                self._cancel_in_progress = False
                self._quit_confirmation_pending = False
                if error is None:
                    _notify(self, f"Live run cancel completed: {status}")
                else:
                    _notify(self, f"Live run cancel failed: {error}")
                self._render_live_monitor()
                if exit_after and error is None:
                    self._exit_app()

            _call_from_thread(self, finish_update)

        _run_background(self, cancel_and_update)

    def _exit_app(self) -> None:
        exit_app = getattr(self, "exit", None)
        if callable(exit_app):
            exit_app()

    def _render_live_monitor(self) -> None:
        if self._workspace == "run":
            self._update_run_widgets()
        _update_widget(self, "#screen-run-monitor", _right_pane_markup(self))
        _update_widget(self, "#screen-home", _left_pane_markup(self))
        _set_widget_classes(self, "#screen-run-monitor", _pane_classes(self, "right"))
        _set_widget_classes(self, "#screen-home", _pane_classes(self, "left"))
        self._update_console_status()

    def _update_run_widgets(self) -> None:
        profile = self._live_run_profile
        if self.live_run_controller.launch is None:
            profile = self._profile_by_name(self._profile_name())
        snapshot = self.live_run_controller.read_live_events()
        if self._loop_run_view is not None:
            self._loop_run_view.set_state(self.live_run_controller, profile)
            self._loop_run_view.rebuild(snapshot=snapshot)
        if self._event_log is not None:
            self._event_log.set_controller(self.live_run_controller)
            self._event_log.rebuild(snapshot=snapshot)

    def _update_console_status(self) -> None:
        _update_widget(self, "#status-bar", _status_bar_markup(self))
        _update_widget(self, "#footer-bar", _footer_markup(self))
        _update_widget(self, "#loop-command-panel", _loop_command_markup(self))
        _update_widget(self, "#loop-settings-panel", _loop_settings_markup(self))
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
    from code_review_loop import tui_loop_widgets

    diagram_class = tui_loop_widgets.loop_diagram_class()
    if diagram_class is None:
        return None
    model = getattr(app, "_loop_model", None)
    if model is None:
        return None
    widget = diagram_class(model)
    app._loop_diagram = widget
    return widget


def _last_run_loop_model(
    cwd: Path,
) -> tuple[Any, str, tui_session.PendingReviewSelection | None] | None:
    from code_review_loop import tui_loop_model
    from code_review_loop.cli import wizard

    lookup = wizard._last_run_state(cwd)
    state = lookup.state
    if state is None or state.profile_name is None:
        return None
    model = tui_loop_model.LoopEditModel.load(state.profile_name, cwd=cwd)
    _apply_wizard_state_to_loop_model(model, state)
    model.mark_replay_baseline()
    origin = state.origin_label or "last run"
    if state.origin_command:
        origin = f"{origin}: {state.origin_command}"
    pending: tui_session.PendingReviewSelection | None = None
    try:
        config = wizard._config_for_state(state, cwd)
        from code_review_loop.cli.config_support import (
            current_git_state_for_latest,
            find_pending_review_candidate,
        )

        current_git_state = current_git_state_for_latest(cwd, config.base)
        candidate = (
            find_pending_review_candidate(
                lookup.summary_path.parent,
                current_git_state=current_git_state,
            )
            if lookup.summary_path is not None
            else None
        )
        compatible = candidate is not None
        if candidate is None and lookup.summary_path is not None:
            candidate = find_pending_review_candidate(
                lookup.summary_path.parent,
                current_git_state=None,
            )
    except (OSError, RuntimeError, ValueError):
        candidate = None
    if candidate is not None:
        git_state = None
        if lookup.summary_path is not None:
            try:
                summary = json.loads(lookup.summary_path.read_text(encoding="utf-8"))
                raw_git_state = (
                    summary.get("git_state") if isinstance(summary, dict) else None
                )
                git_state = raw_git_state if isinstance(raw_git_state, dict) else None
            except (OSError, json.JSONDecodeError):
                pass
        pending = tui_session.PendingReviewSelection(
            path=candidate.path,
            run_dir=candidate.run_dir,
            final_status=candidate.final_status,
            stopped_reason=candidate.stopped_reason,
            excerpt=candidate.excerpt,
            compatible=compatible,
            selected=compatible,
            git_state=git_state,
        )
    return model, origin, pending


def _apply_wizard_state_to_loop_model(model: Any, state: Any) -> None:
    profile = model.profile
    shared_timeout = state.timeout_seconds

    def phase_timeout(value: str) -> str:
        return value or shared_timeout

    pairs = (
        ("pipeline.base", state.base, profile.pipeline.base),
        (
            "pipeline.max_iterations",
            state.max_iterations,
            profile.pipeline.max_iterations,
        ),
        (
            "runtime.inner_check_retries",
            state.inner_check_retries,
            profile.runtime.inner_check_retries,
        ),
        ("pipeline.final_review", state.final_review, profile.pipeline.final_review),
        ("pipeline.checks", state.checks, profile.pipeline.checks),
        (
            "pipeline.check_timeout_seconds",
            phase_timeout(state.check_timeout_seconds),
            profile.pipeline.check_timeout_seconds,
        ),
        ("triage.enabled", state.triage_enabled, profile.triage.enabled),
        (
            "triage.routing.enabled",
            state.routing_enabled,
            profile.triage.routing.enabled,
        ),
        (
            "triage.routing.default_route",
            state.routing_default_route,
            profile.triage.routing.default_route,
        ),
        (
            "triage.routing.strict_on_unavailable_route",
            state.routing_strict,
            profile.triage.routing.strict_on_unavailable_route,
        ),
        (
            "triage.routing.allow_model_escalation",
            state.allow_model_escalation,
            profile.triage.routing.allow_model_escalation,
        ),
        ("review.harness", state.review_harness, profile.review.harness),
        ("review.model", state.review_model, profile.review.model or ""),
        (
            "review.reasoning_effort",
            state.review_reasoning_effort,
            profile.review.reasoning_effort or "",
        ),
        (
            "review.timeout_seconds",
            phase_timeout(state.review_timeout_seconds),
            profile.review.timeout_seconds,
        ),
        ("triage.harness", state.triage_harness, profile.triage.harness),
        ("triage.model", state.triage_model, profile.triage.model or ""),
        (
            "triage.reasoning_effort",
            state.triage_reasoning_effort,
            profile.triage.reasoning_effort or "",
        ),
        (
            "triage.timeout_seconds",
            phase_timeout(state.triage_timeout_seconds),
            profile.triage.timeout_seconds,
        ),
        ("remediation.harness", state.remediation_harness, profile.remediation.harness),
        ("remediation.model", state.remediation_model, profile.remediation.model or ""),
        (
            "remediation.reasoning_effort",
            state.remediation_reasoning_effort,
            profile.remediation.reasoning_effort or "",
        ),
        (
            "remediation.timeout_seconds",
            phase_timeout(state.remediation_timeout_seconds),
            profile.remediation.timeout_seconds,
        ),
        ("commit.enabled", state.commit_after_remediation, profile.commit.enabled),
        ("commit.harness", state.commit_message_harness, profile.commit.harness),
        (
            "commit.message_model",
            state.commit_message_model,
            profile.commit.message_model or "",
        ),
        (
            "commit.reasoning_effort",
            state.commit_reasoning_effort,
            profile.commit.reasoning_effort or "",
        ),
        (
            "commit.timeout_seconds",
            phase_timeout(state.commit_timeout_seconds),
            profile.commit.timeout_seconds,
        ),
    )
    for dotted, value, baseline in pairs:
        if value is not None and value != baseline:
            model.set_field(dotted, value)


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


def _profile_picker_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    picker_class = tui_loop_widgets.profile_picker_class()
    if picker_class is None:
        return None
    widget = picker_class(tui_profiles_state.profile_picker_groups(app.model.snapshot))
    app._profile_picker = widget
    return widget


def _prompt_library_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    library_class = tui_loop_widgets.prompt_library_class()
    if library_class is None:
        return None
    widget = library_class()
    app._prompt_library = widget
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
            lines.append(
                f"{marker} {_phase_summary_line(phase, selected=index == app._selected_phase_index)}"
            )
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
        lines.append(
            f"editable: {_yes_no(profile.triage.prompt is not None)} via revrem config edit"
        )
        lines.append(
            f"value: {tui_state.markup_escape(profile.triage.prompt or '<default triage contract prompt>')}"
        )
    elif phase_name == "commit":
        lines.append("field: commit.message_prompt")
        lines.append(
            f"editable: {_yes_no(profile.commit.message_prompt is not None)} via revrem config edit"
        )
        lines.append(
            "value: "
            + tui_state.markup_escape(
                profile.commit.message_prompt or "<default commit-message prompt>"
            )
        )
    elif phase_name == "review":
        lines.append(
            "source: native codex review prompt or composed external review prompt"
        )
        lines.append(
            "editable: no dedicated profile field; edit harness/model/profile settings"
        )
    elif phase_name == "remediation":
        fragment_names = sorted(
            {
                fragment
                for rule in profile.triage.routing.rule
                for fragment in rule.then.prompt_fragments
            }
        )
        lines.append("source: generated remediation prompt plus route prompt fragments")
        lines.append(
            "editable: route fragments are configured in triage.routing.rule[].then.prompt_fragments"
        )
        lines.append(
            "fragments: "
            + (", ".join(fragment_names) if fragment_names else "none configured")
        )
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
    hints: tuple[tuple[str, str], ...]
    if app._workspace == "profiles":
        hints = (
            ("↑/↓", "Move"),
            ("Enter", "Load"),
            ("d", "Dry-run"),
            ("r", "Run"),
            ("?", "Help"),
        )
    elif app._workspace == "loop":
        hints = (
            ("↑/↓", "Phase"),
            ("Enter", "Details"),
            ("s", "Save"),
            ("r", "Run"),
            ("?", "Help"),
            ("q", "Quit"),
        )
    elif app._workspace == "prompts":
        target = f" for {app._prompt_target_key}" if app._prompt_target_key else ""
        hints = (
            ("↑/↓", "Asset"),
            ("Enter", f"Apply{target}"),
            ("?", "Help"),
            ("q", "Quit"),
        )
    else:
        summary = app.live_run_controller.read_summary()
        reason = summary.get("stopped_reason") if isinstance(summary, dict) else None
        if reason == "review_unknown":
            hints = (
                ("R", "Prepare retry"),
                ("v", "Diagnostics"),
                ("Tab", "Detail view"),
                ("↑/↓", "Scroll"),
                ("o", "Artifacts"),
                ("?", "Help"),
            )
        elif isinstance(summary, dict):
            hints = (
                ("r", "New run"),
                ("c", "Prepare continuation"),
                ("Tab", "Detail view"),
                ("↑/↓", "Scroll"),
                ("o", "Artifacts"),
                ("?", "Help"),
            )
        else:
            hints = (
                ("d", "Dry-run"),
                ("r", "Run"),
                ("k", "Stop"),
                ("Tab", "Detail view"),
                ("o", "Artifacts"),
                ("?", "Help"),
            )
    return "  ".join(
        f"\\[{key}] {tui_state.markup_escape(label)}" for key, label in hints
    )


def _loop_command_markup(app: Any) -> str:
    if app._workspace != "loop":
        return ""
    model = getattr(app, "_loop_model", None)
    profile_text = app._profile_name() or "<none>"
    if model is not None and model.is_user_modified:
        profile_text += " · Modified"
    elif model is not None and model.is_dirty:
        profile_text += " · Replayed settings"
    origin = _origin_detail(app.loop_session.origin_label)
    lines = [
        "[b]NEXT RUN[/]",
        f"Profile: {tui_state.markup_escape(profile_text)}",
    ]
    pending = app.loop_session.pending_review
    if pending is None:
        lines.append("Review input: Fresh review — initial review file: none")
    elif pending.selected and pending.compatible:
        lines.append(
            "Review input: Reuse compatible review — "
            f"{tui_state.markup_escape(_display_path(app, pending.path))}"
        )
    elif pending.selected:
        lines.append(
            "Review input: Validate older review — "
            f"{tui_state.markup_escape(_display_path(app, pending.path))}"
        )
    elif pending.compatible:
        lines.append("Review input: Fresh review — initial review file: none")
        lines.append(
            "Compatible review available: "
            f"{tui_state.markup_escape(_display_path(app, pending.path))} (u reuse · v details)"
        )
    else:
        lines.append("Review input: Fresh review — initial review file: none")
        lines.append(
            "Older review available: "
            f"{tui_state.markup_escape(_display_path(app, pending.path))} (u validate · v details)"
        )
    if origin:
        lines.append(f"Loaded from: {_origin_summary(origin)}")
    lines.append(
        "Launch: effective working copy of "
        f"{tui_state.markup_escape(app._profile_name() or '<none>')} · snapshot saved with run"
    )
    return "\n".join(lines)


def _loop_settings_markup(app: Any) -> str:
    loop_model = getattr(app, "_loop_model", None)
    profile = loop_model.profile if loop_model is not None else None
    if profile is None:
        return "RUN SETTINGS\nNo active profile."
    assert loop_model is not None
    base = loop_model.field_value("pipeline.base", profile.pipeline.base)
    iterations = loop_model.field_value(
        "pipeline.max_iterations", profile.pipeline.max_iterations
    )
    raw_final = loop_model.field_value(
        "pipeline.final_review", profile.pipeline.final_review
    )
    final_enabled = (
        raw_final.strip().lower() in {"true", "yes", "on", "1"}
        if isinstance(raw_final, str)
        else bool(raw_final)
    )
    return "\n".join(
        (
            "RUN SETTINGS",
            f"Base: {base} | Max iterations: {iterations} | Final review: {'on' if final_enabled else 'off'}",
            "b edit base · i edit max iterations · F toggle final review",
        )
    )


def _live_hint(app: Any) -> str:
    if app._cancel_in_progress:
        return "live: cancelling child process"
    if app._quit_confirmation_pending:
        return "live: press q again to cancel and quit"
    if app._pending_live_confirmation_profile:
        return f"live: press r again to start {app._pending_live_confirmation_profile}"
    if app._live_run_active():
        return "live: running; press k to cancel"
    return f"live: {_operator_run_status(app.live_run_controller.status)}"


def _command_preview(app: Any) -> str:
    profile = app._profile_by_name(app._profile_name())
    if profile is None:
        return "revrem config new final-pr"
    if app._workspace == "profiles":
        return tui_state.launch_plan(profile, dry_run=False).shell_command
    return cast(str, app._profile_launch_plan(profile, dry_run=False).shell_command)


def _splash_markup() -> str:
    return "\n".join(
        (
            "   ____             ____                 ",
            "  |  _ \\ _____   _ |  _ \\ ___ _ __ ___  ",
            "  | |_) / _ \\ \\ / /| |_) / _ \\ '_ ` _ \\ ",
            "  |  _ <  __/\\ V / |  _ <  __/ | | | | |",
            "  |_| \\_\\___| \\_/  |_| \\_\\___|_| |_| |_|",
            "",
            "        REVIEW  >>  REMEDIATE  >>  VERIFY",
            "        local automation control deck",
            "",
            "        press any key to start",
        )
    )


def _startup_markup(app: Any) -> str:
    error = getattr(app, "_bootstrap_error", None)
    if error:
        return "\n".join(
            (
                "RevRem could not load the workbench.",
                "",
                _truncate(str(error), 500),
                "",
                "Press q to quit, then correct the profile or catalog error.",
            )
        )
    loading = bool(getattr(app, "_bootstrap_loading", False))
    splash = bool(getattr(app, "_splash_visible", False))
    if splash:
        text = _splash_markup()
        if loading:
            suffix = (
                "Still loading profiles, catalog, and repository history…"
                if getattr(app, "_bootstrap_slow", False)
                else "Loading profiles, catalog, and repository history…"
            )
            return f"{text}\n\n        {suffix}"
        return text
    if loading:
        message = (
            "Still loading profiles, catalog, and repository history…"
            if getattr(app, "_bootstrap_slow", False)
            else "Loading RevRem workbench…"
        )
        return f"{message}\n\nPress q to quit."
    return ""


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
    text = f"{marker} {phase.name}: " + ", ".join(
        tui_state.markup_escape(item) for item in details
    )
    if selected:
        return f"[status-info]{text}[/]"
    if not phase.enabled:
        return f"[muted]{text}[/]"
    return text


def _phase_marker(phase: tui_state.PhaseView) -> str:
    if not phase.enabled:
        return "[ ]"
    return "[[ok]]"


def _phase_detail_lines(
    profile: profiles.Profile, phase: tui_state.PhaseView
) -> list[str]:
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
    lines.append(
        "  -> final review"
        if profile.pipeline.final_review
        else "  -> final review off"
    )
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
    return [
        "",
        f"[b]{label}[/]",
        *[tui_state.markup_escape(line) for line in lines[-limit:]],
    ]


def _summary_lines(controller: tui_run_controller.LiveRunController) -> list[str]:
    if controller.launch is None:
        return ["", "[b]summary[/]", "No live run has been launched."]
    summary_path = controller.launch.artifact_dir / "summary.json"
    if not summary_path.is_file():
        return [
            "",
            "[b]summary[/]",
            f"waiting for {tui_state.markup_escape(str(summary_path))}",
        ]
    return ["", "[b]summary[/]", tui_state.markup_escape(str(summary_path))]


def _home_markup(app: Any) -> str:
    snapshot = app.model.snapshot
    implemented = [
        harness.name for harness in snapshot.harnesses if harness.implemented
    ]
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
    profiles_by_name = {
        profile.name: profile for profile in app.model.snapshot.profiles
    }
    ordered = []
    if selected and selected in profiles_by_name:
        ordered.append(profiles_by_name[selected])
    ordered.extend(
        profile for profile in app.model.snapshot.profiles if profile.name != selected
    )
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
        lines.append(
            f"{phase.name}: "
            + ", ".join(tui_state.markup_escape(item) for item in details)
        )
    if profile.triage.routing.enabled:
        route_count = len(profile.triage.routes)
        route = profile.triage.routing.default_route or "none"
        lines.append(
            f"routing: default={tui_state.markup_escape(route)} routes={route_count}"
        )
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


def _screen_by_name(
    model: tui_state.TuiShellModel, name: str
) -> tui_state.TuiScreen | None:
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
        live_hint = (
            f"confirm run: press r again for {app._pending_live_confirmation_profile}"
        )
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
        lines.append(
            f"artifacts: {tui_state.markup_escape(str(controller.launch.artifact_dir))}"
        )
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
            lines.append(
                f"  {tui_state.markup_escape(tui_state.event_row_text(event))}"
            )
    return "\n".join(lines)


def _status_bar_markup(app: Any) -> str:
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
    workspace = app._workspace.capitalize()
    tabs = []
    for key, name in zip(
        ("1", "2", "3", "4"),
        ("Loop", "Run", "Profiles", "Prompts"),
        strict=True,
    ):
        label = f"{key} {name}"
        tabs.append(f"[workspace-active]{label}[/]" if name == workspace else label)
    return (
        f"RevRem · {tui_state.markup_escape(Path(app.model.snapshot.cwd).name or app.model.snapshot.cwd)}"
        f" · {tui_state.markup_escape(workspace)} · "
        f"{tui_state.markup_escape(_operator_run_status(status))}"
        f"{tui_state.markup_escape(pending)}\n"
        f"{' · '.join(tabs)} · ? Help · q Quit"
    )


def _status_bar_classes(status: tui_run_controller.RunControllerStatus) -> str:
    return f"status-{status}"


def _operator_run_status(status: str) -> str:
    return {
        "completed-clear": "complete",
        "completed-findings": "action needed",
        "completed-unknown": "needs attention",
        "setup-failed": "setup failed",
        "failed-forced-cleanup": "failed after forced cleanup",
        "interrupted-before-run-initialized": "interrupted",
    }.get(status, status)


def _origin_summary(origin: str | None, *, now: datetime | None = None) -> str:
    if not origin:
        return "-"
    label, _, _command = origin.partition(": ")
    match = re.search(r"\bfrom\s+(\S+)", label)
    if match is None:
        return "previous run"
    try:
        occurred = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return "previous run"
    now = now or datetime.now(occurred.tzinfo)  # det-exempt: human display clock
    days = (now.date() - occurred.date()).days
    if days == 0:
        date_label = "today"
    elif days == 1:
        date_label = "yesterday"
    elif 2 <= days < 7:
        date_label = occurred.strftime("%A")
    elif occurred.year == now.year:
        date_label = f"{occurred.day} {occurred.strftime('%B')}"
    else:
        date_label = f"{occurred.day}-{occurred.month}-{occurred.strftime('%y')}"
    return f"[status-info]{date_label}[/] [muted]{occurred:%H:%M}[/]"


def _origin_detail(origin: str | None) -> str:
    if not origin:
        return ""
    return origin


def _display_path(app: Any, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(app.model.snapshot.cwd).resolve()))
    except ValueError:
        return str(path)


def _profile_base(app: Any) -> str:
    profile = app._profile_by_name(app._profile_name())
    return str(profile.pipeline.base) if profile is not None else "-"


def _cancel_active_modal(app: Any) -> bool:
    screen = getattr(app, "screen", None)
    if screen is None or screen is app:
        return False
    if _ModalScreen is not None and not isinstance(screen, _ModalScreen):
        return False
    action_cancel = getattr(screen, "action_cancel", None)
    if callable(action_cancel):
        action_cancel()
        return True
    return False


def _help_markup(*, visible: bool) -> str:
    return (
        "Help\nPress ? or h for keybindings." if not visible else _generic_help_text()
    )


def _help_text(app: Any) -> str:
    lines = [
        "HELP",
        "",
        "Navigation",
        "  Up/Down or j/k move · Enter expands/selects · Esc closes or clears focus",
        "  1 Loop · 2 Run · 3 Profiles · 4 Prompts · q Quit",
        "",
    ]
    if app._workspace == "loop":
        phase = (
            app._loop_diagram.current_phase()
            if getattr(app, "_loop_diagram", None) is not None
            else "review"
        )
        lines.extend(
            (
                "Run settings",
                "  b Base · i Max iterations · F Final review",
                "",
                f"Selected phase: {phase}",
                f"  {_phase_help_text(phase)}",
                "",
                "Review input",
                "  u Toggle reuse/validation · v Details",
                "",
                "Run",
                "  d Dry-run · r Confirm/start · k Cancel · s Save profile",
            )
        )
    elif app._workspace == "run":
        lines.extend(("Run", "  l Logs/events · o Artifacts · k Cancel · d Dry-run"))
    elif app._workspace == "profiles":
        lines.extend(
            (
                "Profiles",
                "  Enter load · n New · c Clone · e Edit · x Export · Delete remove",
            )
        )
    else:
        lines.extend(("Prompts", "  Enter apply · Esc return"))
    return "\n".join(lines)


def _generic_help_text() -> str:
    return "\n".join(
        (
            "HELP",
            "Up/Down move · Enter select · Esc close",
            "1 Loop · 2 Run · 3 Profiles · 4 Prompts · q Quit",
            "Loop: b base · i max iterations · F final review · s save",
            "Run: d dry-run · r start · k cancel",
        )
    )


def _phase_help_text(phase: str) -> str:
    return {
        "review": "m Harness · M Model · f Effort · t Timeout",
        "triage": "Space On/off · m Harness · M Model · f Effort · t Timeout · e Prompt · g Library · a Route",
        "remediation": "m Harness · M Model · f Effort · t Timeout",
        "checks": "p Choose checks · e Custom commands · t Timeout · I Check-failure retries",
        "commit": "Space On/off · m Harness · M Model · f Effort · t Timeout · e Message prompt · g Library",
    }.get(phase, "Enter expand")


def _check_picker_text(choices: tuple[_CheckChoice, ...], selected_index: int) -> str:
    lines = [
        "CHOOSE VERIFICATION CHECKS",
        "Built-in worktree cleanliness always runs.",
        "",
    ]
    group: str | None = None
    for index, choice in enumerate(choices):
        if choice.group != group:
            group = choice.group
            lines.append(f"-- {group} --")
        marker = ">" if index == selected_index else " "
        lines.append(f"{marker} {choice.label}")
    if choices:
        selected = choices[max(0, min(selected_index, len(choices) - 1))]
        lines.extend(("", "Commands"))
        if selected.checks is None:
            lines.append("  Enter commands manually after selecting this option.")
        elif selected.checks:
            lines.extend(
                f"  {index}. {command}"
                for index, command in enumerate(selected.checks, 1)
            )
        else:
            lines.append("  No configured commands; built-in cleanliness only.")
    return "\n".join(lines)


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
