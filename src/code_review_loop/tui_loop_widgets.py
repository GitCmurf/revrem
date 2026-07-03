"""Lazy Textual widgets for the editable loop screen."""

from __future__ import annotations

from typing import Any

from code_review_loop import (
    harnesses,
    profiles,
    tui_loop_state,
    tui_profiles_state,
    tui_prompts_state,
)


def _harness_choices() -> tuple[str, ...]:
    implemented = sorted(
        name for name, spec in harnesses.HARNESS_REGISTRY.items() if spec.implemented
    )
    if "codex" in implemented:
        implemented.remove("codex")
        implemented.insert(0, "codex")
    return tuple(implemented)


HARNESS_CHOICES = _harness_choices()
EFFORT_CHOICES = profiles.REASONING_EFFORT_CHOICES
_PHASE_CARD_CLASS: type[Any] | None = None
_TRIAGE_ROUTES_TABLE_CLASS: type[Any] | None = None
_LOOP_DIAGRAM_CLASS: type[Any] | None = None
_LOOP_RUN_VIEW_CLASS: type[Any] | None = None
_EVENT_LOG_CLASS: type[Any] | None = None
_PROFILE_PICKER_CLASS: type[Any] | None = None
_PROMPT_LIBRARY_CLASS: type[Any] | None = None
_ROUTE_EDIT_MODAL_CLASS: type[Any] | None = None


def _load_components() -> tuple[Any, Any, Any] | None:
    from code_review_loop import tui

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if tui._Static is object or tui._Vertical is None or tui._Horizontal is None:
        return None
    return tui._Static, tui._Vertical, tui._Horizontal


def _profile_dotted_value(profile: profiles.Profile, dotted: str) -> Any:
    cursor: Any = profile
    for part in dotted.split("."):
        cursor = cursor[part] if isinstance(cursor, dict) else getattr(cursor, part)
    return cursor


def phase_card_class() -> type[Any] | None:
    global _PHASE_CARD_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, _vertical_cls, _horizontal_cls = loaded
    if _PHASE_CARD_CLASS is not None:
        return _PHASE_CARD_CLASS

    class PhaseCard(static_cls):  # type: ignore[misc, valid-type]
        def __init__(
            self, model: Any, phase_name: str, *, focused: bool, expanded: bool
        ) -> None:
            super().__init__(
                "",
                id=f"phase-card-{phase_name}",
                classes="phase-card",
                markup=False,
            )
            self.model = model
            self.phase_name = phase_name
            self.focused = focused
            self.expanded = expanded
            self.rebuild()

        def set_state(self, *, focused: bool, expanded: bool) -> None:
            self.focused = focused
            self.expanded = expanded
            self.rebuild()

        def rebuild(self) -> None:
            lines = tui_loop_state.phase_card_lines(
                self.model,
                self.phase_name,
                focused=self.focused,
                expanded=self.expanded,
            )
            self.update("\n".join(lines))

    _PHASE_CARD_CLASS = PhaseCard
    return _PHASE_CARD_CLASS


def triage_routes_table_class() -> type[Any] | None:
    global _TRIAGE_ROUTES_TABLE_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, _vertical_cls, _horizontal_cls = loaded
    if _TRIAGE_ROUTES_TABLE_CLASS is not None:
        return _TRIAGE_ROUTES_TABLE_CLASS

    class TriageRoutesTable(static_cls):  # type: ignore[misc, valid-type]
        def __init__(self, model: Any) -> None:
            super().__init__(
                "",
                id="triage-routes-table",
                classes="triage-routes-table",
                markup=False,
            )
            self.model = model
            self.selected_route: str | None = None
            self.rebuild()

        def rebuild(self) -> None:
            lines = tui_loop_state.triage_routes_lines(
                self.model, selected_route=self.selected_route
            )
            self.update("\n".join(lines))

    _TRIAGE_ROUTES_TABLE_CLASS = TriageRoutesTable
    return _TRIAGE_ROUTES_TABLE_CLASS


def loop_diagram_class() -> type[Any] | None:
    global _LOOP_DIAGRAM_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, vertical_cls, horizontal_cls = loaded
    card_cls = phase_card_class()
    routes_cls = triage_routes_table_class()
    if card_cls is None or routes_cls is None:
        return None
    phase_card_cls: Any = card_cls
    route_table_cls: Any = routes_cls
    if _LOOP_DIAGRAM_CLASS is not None:
        return _LOOP_DIAGRAM_CLASS

    class LoopDiagram(vertical_cls):  # type: ignore[misc, valid-type]
        can_focus = True

        def __init__(self, model: Any) -> None:
            super().__init__(id="loop-diagram", classes="loop-diagram")
            self.model = model
            self.focused_index = 0
            self.expanded = False
            self._header = static_cls("", id="loop-header", markup=False)
            self._gutters: dict[str, Any] = {}
            self._cards: dict[str, Any] = {}
            self._routes_table: Any | None = None
            self.route_mode = False
            self.selected_route_index = 0

        @property
        def is_dirty(self) -> bool:
            return bool(self.model.is_dirty)

        def compose(self):
            yield self._header
            for index, phase in enumerate(tui_loop_state.LOOP_PHASES):
                with horizontal_cls(id=f"loop-row-{phase}", classes="loop-row"):
                    gutter = static_cls(
                        "",
                        id=f"phase-gutter-{phase}",
                        classes="phase-gutter",
                        markup=False,
                    )
                    self._gutters[phase] = gutter
                    yield gutter
                    card = phase_card_cls(
                        self.model,
                        phase,
                        focused=index == self.focused_index,
                        expanded=self.expanded and index == self.focused_index,
                    )
                    self._cards[phase] = card
                    yield card
            self._routes_table = route_table_cls(self.model)
            yield self._routes_table

        def on_mount(self) -> None:
            self.rebuild()

        def set_model(self, model: Any) -> None:
            self.model = model
            for card in self._cards.values():
                card.model = model
            if self._routes_table is not None:
                self._routes_table.model = model
            self.focused_index = 0
            self.expanded = False
            self.route_mode = False
            self.selected_route_index = 0
            self.rebuild()

        def current_phase(self) -> str:
            max_index = len(tui_loop_state.LOOP_PHASES) - 1
            self.focused_index = max(0, min(self.focused_index, max_index))
            return tui_loop_state.LOOP_PHASES[self.focused_index]

        def move(self, delta: int) -> None:
            if self.route_mode:
                route_names = self.route_names()
                if route_names:
                    self.selected_route_index = (
                        self.selected_route_index + delta
                    ) % len(route_names)
                    self.rebuild()
                return
            self.focused_index = (self.focused_index + delta) % len(
                tui_loop_state.LOOP_PHASES
            )
            self.rebuild()

        def route_names(self) -> tuple[str, ...]:
            return tuple(
                row.name for row in tui_loop_state.triage_route_rows(self.model)
            )

        def selected_route(self) -> str | None:
            names = self.route_names()
            if not names:
                return None
            self.selected_route_index = max(
                0, min(self.selected_route_index, len(names) - 1)
            )
            return names[self.selected_route_index]

        def enter_route_mode(self) -> bool:
            if self.current_phase() != "triage" or not self.route_names():
                return False
            self.route_mode = True
            self.expanded = True
            self.rebuild()
            return True

        def exit_route_mode(self) -> None:
            self.route_mode = False
            self.rebuild()

        def toggle_enabled(self) -> None:
            dotted = tui_loop_state.PHASE_DOTTED[self.current_phase()].get("enabled")
            if dotted is None:
                return
            phase = self.current_phase()
            current = _phase_enabled(self.model, phase, dotted)
            self.model.set_field(dotted, "false" if current else "true")
            self.rebuild()

        def cycle_field(self, key: str) -> None:
            dotted = tui_loop_state.PHASE_DOTTED[self.current_phase()].get(key)
            if dotted is None:
                return
            choices = HARNESS_CHOICES if key == "harness" else EFFORT_CHOICES
            if not choices:
                return
            # Fall back to the resolved profile value when there is no unsaved
            # overlay so cycling advances from what the user currently sees.
            current = str(
                self.model.field_value(
                    dotted, _profile_dotted_value(self.model.profile, dotted)
                )
            )
            try:
                index = choices.index(current)
            except ValueError:
                index = -1
            self.model.set_field(dotted, choices[(index + 1) % len(choices)])
            self.rebuild()

        def set_text_field(self, key: str, value: str) -> None:
            dotted = tui_loop_state.PHASE_DOTTED[self.current_phase()].get(key)
            if dotted is None:
                return
            self.model.set_field(dotted, value)
            self.rebuild()

        def set_loop_meta_field(self, key: str, value: str) -> None:
            dotted = tui_loop_state.LOOP_META_DOTTED[key]
            self.model.set_field(dotted, value)
            self.rebuild()

        def toggle_final_review(self) -> None:
            dotted = tui_loop_state.LOOP_META_DOTTED["final_review"]
            current = bool(
                self.model.field_value(dotted, self.model.profile.pipeline.final_review)
            )
            self.model.set_field(dotted, "false" if current else "true")
            self.rebuild()

        def rebuild(self) -> None:
            self.current_phase()
            meta = tui_loop_state.loop_rail_meta(self.model)
            self._header.update(tui_loop_state.loop_header_text(self.model))
            for index, phase in enumerate(tui_loop_state.LOOP_PHASES):
                gutter = self._gutters.get(phase)
                if gutter is not None:
                    gutter.update(tui_loop_state.phase_gutter(phase, meta))
                card = self._cards.get(phase)
                if card is not None:
                    card.set_state(
                        focused=index == self.focused_index,
                        expanded=self.expanded and index == self.focused_index,
                    )
            if self._routes_table is not None:
                self._routes_table.display = self.current_phase() == "triage"
                self._routes_table.selected_route = (
                    self.selected_route() if self.route_mode else None
                )
                self._routes_table.rebuild()
            self.refresh()

    _LOOP_DIAGRAM_CLASS = LoopDiagram
    return _LOOP_DIAGRAM_CLASS


def profile_picker_class() -> type[Any] | None:
    global _PROFILE_PICKER_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, _vertical_cls, _horizontal_cls = loaded
    if _PROFILE_PICKER_CLASS is not None:
        return _PROFILE_PICKER_CLASS

    class ProfilePicker(static_cls):  # type: ignore[misc, valid-type]
        can_focus = True

        def __init__(
            self, rows: tuple[tui_profiles_state.ProfilePickerRow, ...]
        ) -> None:
            super().__init__(
                "", id="profile-picker", classes="profile-picker", markup=False
            )
            self.rows = rows
            self.selected_index = 0
            self.rebuild()

        def set_rows(
            self, rows: tuple[tui_profiles_state.ProfilePickerRow, ...]
        ) -> None:
            self.rows = rows
            self.selected_index = (
                0 if not rows else min(self.selected_index, len(rows) - 1)
            )

        def move(self, delta: int) -> None:
            if self.rows:
                self.selected_index = (self.selected_index + delta) % len(self.rows)
                self.rebuild()

        def selected_name(self) -> str | None:
            if not self.rows:
                return None
            return self.rows[self.selected_index].name

        def on_mount(self) -> None:
            self.rebuild()

        def rebuild(self) -> None:
            lines = ["PROFILES  load a saved loop", ""]
            group = None
            if not self.rows:
                lines.append("No profiles found.")
            for index, row in enumerate(self.rows):
                if row.group != group:
                    group = row.group
                    lines.append(f"-- {group} --")
                pointer = ">" if index == self.selected_index else " "
                lines.append(f"{pointer} {row.name}  {row.source_label}  {row.summary}")
                if row.description:
                    lines.append(f"  {row.description}")
            self.update("\n".join(lines))

    _PROFILE_PICKER_CLASS = ProfilePicker
    return _PROFILE_PICKER_CLASS


def prompt_library_class() -> type[Any] | None:
    global _PROMPT_LIBRARY_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, _vertical_cls, _horizontal_cls = loaded
    if _PROMPT_LIBRARY_CLASS is not None:
        return _PROMPT_LIBRARY_CLASS

    class PromptLibrary(static_cls):  # type: ignore[misc, valid-type]
        can_focus = True

        def __init__(self) -> None:
            super().__init__(
                "", id="prompt-library", classes="prompt-library", markup=False
            )
            self.assets = tui_prompts_state.prompt_inventory()
            self.selected_index = 0
            self.rebuild()

        def move(self, delta: int) -> None:
            if self.assets:
                self.selected_index = (self.selected_index + delta) % len(self.assets)
                self.rebuild()

        def selected_asset(self) -> tui_prompts_state.PromptAsset | None:
            if not self.assets:
                return None
            return self.assets[self.selected_index]

        def on_mount(self) -> None:
            self.rebuild()

        def rebuild(self) -> None:
            lines = ["PROMPTS  library", ""]
            if not self.assets:
                lines.append("No prompt assets found.")
            for index, asset in enumerate(self.assets):
                pointer = ">" if index == self.selected_index else " "
                lines.append(f"{pointer} {asset.name}  {asset.kind} · {asset.trust}")
            asset = self.selected_asset()
            if asset is not None:
                lines.extend(("", asset.preview))
            self.update("\n".join(lines))

    _PROMPT_LIBRARY_CLASS = PromptLibrary
    return _PROMPT_LIBRARY_CLASS


def route_edit_modal_class() -> type[Any] | None:
    global _ROUTE_EDIT_MODAL_CLASS
    from code_review_loop import tui

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if (
        tui._ModalScreen is None
        or tui._Vertical is None
        or tui._Input is None
        or tui._Button is None
        or tui._Select is None
        or tui._Static is object
    ):
        return None
    if _ROUTE_EDIT_MODAL_CLASS is not None:
        return _ROUTE_EDIT_MODAL_CLASS

    modal_screen: Any = tui._ModalScreen
    vertical_cls: Any = tui._Vertical
    static_cls: Any = tui._Static
    input_cls: Any = tui._Input
    button_cls: Any = tui._Button
    select_cls: Any = tui._Select

    class RouteEditModal(modal_screen):  # type: ignore[misc, valid-type]
        BINDINGS = [
            tui._binding(
                "escape", "cancel", "Cancel", priority=True, binding_cls=tui._Binding
            )
        ]

        def __init__(
            self,
            *,
            route: str,
            values: dict[str, str],
            route_names: tuple[str, ...] = (),
        ) -> None:
            super().__init__()
            self.route = route
            self.values = values
            self.route_names = route_names

        def compose(self):
            with vertical_cls(id="route-edit-dialog"):
                yield static_cls(
                    f"Route: {self.route}", id="route-edit-title", markup=False
                )
                yield static_cls("harness", markup=False)
                yield select_cls(
                    _select_options(
                        _choices_with_current(
                            HARNESS_CHOICES, self.values.get("harness", "")
                        )
                    ),
                    allow_blank=False,
                    value=_select_value(
                        self.values.get("harness", ""), HARNESS_CHOICES
                    ),
                    id="route-edit-harness",
                )
                yield static_cls("model", markup=False)
                yield input_cls(
                    value=self.values.get("model", ""), id="route-edit-model"
                )
                yield static_cls("reasoning_effort", markup=False)
                yield select_cls(
                    _select_options(
                        _choices_with_current(
                            EFFORT_CHOICES, self.values.get("reasoning_effort", "")
                        )
                    ),
                    allow_blank=True,
                    value=_select_value(
                        self.values.get("reasoning_effort", ""),
                        EFFORT_CHOICES,
                        blank_ok=True,
                    ),
                    id="route-edit-reasoning_effort",
                )
                yield static_cls("timeout_seconds", markup=False)
                yield input_cls(
                    value=self.values.get("timeout_seconds", ""),
                    id="route-edit-timeout_seconds",
                )
                yield static_cls("sandbox", markup=False)
                yield select_cls(
                    _select_options(
                        _choices_with_current(
                            profiles.EXEC_SANDBOX_CHOICES,
                            self.values.get("sandbox", ""),
                        )
                    ),
                    allow_blank=False,
                    value=_select_value(
                        self.values.get("sandbox", ""), profiles.EXEC_SANDBOX_CHOICES
                    ),
                    id="route-edit-sandbox",
                )
                yield static_cls("fallback", markup=False)
                fallback_choices = tuple(
                    name for name in self.route_names if name != self.route
                )
                yield select_cls(
                    _select_options(
                        _choices_with_current(
                            fallback_choices, self.values.get("fallback", "")
                        )
                    ),
                    allow_blank=True,
                    value=_select_value(
                        self.values.get("fallback", ""), fallback_choices, blank_ok=True
                    ),
                    id="route-edit-fallback",
                )
                yield button_cls("Save route", id="route-edit-save", variant="primary")
                yield static_cls(
                    "Enter in a text field saves the row | Esc cancels", markup=False
                )

        def on_mount(self) -> None:
            query_one = getattr(self, "query_one", None)
            set_focus = getattr(self, "set_focus", None)
            if callable(query_one) and callable(set_focus):
                set_focus(query_one("#route-edit-harness"))

        def on_input_submitted(self, event: Any) -> None:
            self._submit()

        def on_button_pressed(self, event: Any) -> None:
            if getattr(getattr(event, "button", None), "id", "") == "route-edit-save":
                self._submit()

        def _submit(self) -> None:
            values: dict[str, str] = {}
            for field in (
                "harness",
                "model",
                "reasoning_effort",
                "timeout_seconds",
                "sandbox",
                "fallback",
            ):
                widget = self.query_one(f"#route-edit-{field}")
                if isinstance(widget, select_cls):
                    value = widget.value
                    values[field] = "" if value == select_cls.NULL else str(value)
                else:
                    values[field] = str(getattr(widget, "value", ""))
            self.dismiss((self.route, values))

        def action_cancel(self) -> None:
            self.dismiss(None)

    _ROUTE_EDIT_MODAL_CLASS = RouteEditModal
    return _ROUTE_EDIT_MODAL_CLASS


def _choices_with_current(
    choices: tuple[str, ...], current: str | None
) -> tuple[str, ...]:
    if current and current not in choices:
        return choices + (current,)
    return choices


def _select_options(choices: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((choice, choice) for choice in choices)


def _select_value(
    current: str | None, choices: tuple[str, ...], *, blank_ok: bool = False
) -> Any:
    from code_review_loop import tui

    if current:
        return current
    if blank_ok:
        return tui._Select.NULL
    return choices[0] if choices else tui._Select.NULL


def loop_run_view_class() -> type[Any] | None:
    global _LOOP_RUN_VIEW_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, vertical_cls, horizontal_cls = loaded
    if _LOOP_RUN_VIEW_CLASS is not None:
        return _LOOP_RUN_VIEW_CLASS

    class LoopRunView(vertical_cls):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(id="loop-run", classes="loop-run")
            self.controller: Any | None = None
            self.profile: Any | None = None
            self._header = static_cls("", id="loop-run-header", markup=False)
            self._gutters: dict[str, Any] = {}
            self._phases: dict[str, Any] = {}

        def compose(self):
            yield self._header
            for phase in tui_loop_state.LOOP_PHASES:
                with horizontal_cls(id=f"run-row-{phase}", classes="run-row"):
                    gutter = static_cls(
                        "",
                        id=f"run-gutter-{phase}",
                        classes="phase-gutter",
                        markup=False,
                    )
                    self._gutters[phase] = gutter
                    yield gutter
                    status = static_cls(
                        "",
                        id=f"run-phase-{phase}",
                        classes="run-phase",
                        markup=False,
                    )
                    self._phases[phase] = status
                    yield status

        def on_mount(self) -> None:
            self.rebuild()

        def set_state(self, controller: Any, profile: Any | None) -> None:
            self.controller = controller
            self.profile = profile

        def rebuild(self, *, snapshot: Any | None = None) -> None:
            from code_review_loop import tui_run_state

            if self.controller is None or self.profile is None:
                self._header.update("No active run.")
                self._clear_rows()
                self.refresh()
                return
            if (
                hasattr(self.controller, "launch")
                and self.controller.launch is None
                and getattr(self.controller, "status", "idle") == "idle"
            ):
                self._header.update("No active run.")
                self._clear_rows()
                self.refresh()
                return
            if snapshot is None:
                snapshot = self.controller.read_live_events()
            if snapshot.error:
                self._header.update(f"events: unavailable ({snapshot.error})")
                self._clear_rows()
                self.refresh()
                return
            if not snapshot.ready:
                self._header.update("events: waiting for events.jsonl")
                self._clear_rows()
                self.refresh()
                return

            view = tui_run_state.run_loop_view(snapshot.events, self.profile)
            status_by_phase = {phase.name: phase for phase in view.phases}
            iteration = (
                f"iteration {view.iteration}/{view.max_iterations}"
                if view.iteration is not None
                else f"max {view.max_iterations}"
            )
            truncated = " · events truncated" if snapshot.truncated else ""
            self._header.update(
                f"RUN · {self.profile.name} · {self.controller.status} · {iteration}{truncated}"
            )
            rail_meta = tui_loop_state.loop_rail_meta(self.profile)
            for phase in tui_loop_state.LOOP_PHASES:
                gutter = self._gutters.get(phase)
                if gutter is not None:
                    gutter.update(tui_loop_state.phase_gutter(phase, rail_meta))
                status_widget = self._phases.get(phase)
                if status_widget is None:
                    continue
                status = status_by_phase[phase]
                glyph = tui_run_state.RUN_STATE_GLYPHS.get(status.state, "·")
                detail = f" · {status.detail}" if status.detail else ""
                if phase == "checks" and view.inner_check_retries > 0:
                    retry = (
                        f" · inner retry {view.inner_retry}/{view.inner_check_retries}"
                    )
                    detail = f"{detail}{retry}"
                status_widget.update(f"{glyph} {phase} · {status.state}{detail}")
            self.refresh()

        def _clear_rows(self) -> None:
            for gutter in self._gutters.values():
                gutter.update("")
            for status in self._phases.values():
                status.update("")

    _LOOP_RUN_VIEW_CLASS = LoopRunView
    return _LOOP_RUN_VIEW_CLASS


def event_log_class() -> type[Any] | None:
    global _EVENT_LOG_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, _vertical_cls, _horizontal_cls = loaded
    if _EVENT_LOG_CLASS is not None:
        return _EVENT_LOG_CLASS

    class EventLog(static_cls):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__("", id="event-log", classes="event-log", markup=False)
            self.controller: Any | None = None
            self.show_logs = False

        def set_controller(self, controller: Any) -> None:
            self.controller = controller

        def on_mount(self) -> None:
            self.rebuild()

        def rebuild(self, *, snapshot: Any | None = None) -> None:
            from code_review_loop import tui_run_state

            if self.controller is None:
                self.update("events: waiting for a run")
                return
            if self.show_logs:
                stdout = tuple(self.controller.stdout_lines())[-8:]
                stderr = tuple(self.controller.stderr_lines())[-8:]
                lines = ["logs"]
                lines.extend(f"stdout: {line}" for line in stdout)
                lines.extend(f"stderr: {line}" for line in stderr)
                self.update(
                    "\n".join(lines)
                    if len(lines) > 1
                    else "logs\nNo captured lines yet."
                )
                return
            if snapshot is None:
                snapshot = self.controller.read_live_events()
            if snapshot.error:
                self.update(f"events: unavailable ({snapshot.error})")
                return
            if not snapshot.ready:
                self.update("events: waiting for events.jsonl")
                return
            lines = list(tui_run_state.event_tail_lines(snapshot.events, limit=8))
            if snapshot.truncated:
                lines.insert(0, "events: truncated")
            self.update("\n".join(("events", *lines)) if lines else "events\n…")

    _EVENT_LOG_CLASS = EventLog
    return _EVENT_LOG_CLASS


def _phase_enabled(model: Any, phase: str, dotted: str) -> bool:
    profile = model.profile
    if phase == "triage":
        fallback = profile.triage.enabled
    elif phase == "commit":
        fallback = profile.commit.enabled
    else:
        fallback = True
    return bool(model.field_value(dotted, fallback))
