"""Lazy Textual widgets for the editable loop screen."""

from __future__ import annotations

from typing import Any

from code_review_loop import harnesses, profiles, tui_loop_state


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


def _load_components() -> tuple[Any, Any] | None:
    from code_review_loop import tui

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if tui._Static is object or tui._Vertical is None:
        return None
    return tui._Static, tui._Vertical


def phase_card_class() -> type[Any] | None:
    global _PHASE_CARD_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, _vertical_cls = loaded
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
    static_cls, _vertical_cls = loaded
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
            self.rebuild()

        def rebuild(self) -> None:
            lines = tui_loop_state.triage_routes_lines(self.model)
            self.update("\n".join(lines))

    _TRIAGE_ROUTES_TABLE_CLASS = TriageRoutesTable
    return _TRIAGE_ROUTES_TABLE_CLASS


def loop_diagram_class() -> type[Any] | None:
    global _LOOP_DIAGRAM_CLASS
    loaded = _load_components()
    if loaded is None:
        return None
    static_cls, vertical_cls = loaded
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
            self._rail = static_cls("", id="loop-rail", markup=False)
            self._cards: dict[str, Any] = {}
            self._routes_table: Any | None = None

        @property
        def is_dirty(self) -> bool:
            return bool(self.model.is_dirty)

        def compose(self):
            yield self._header
            yield self._rail
            for index, phase in enumerate(tui_loop_state.LOOP_PHASES):
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

        def render(self) -> str:
            lines = [tui_loop_state.loop_header_text(self.model)]
            meta = tui_loop_state.loop_rail_meta(self.model)
            for phase in tui_loop_state.LOOP_PHASES:
                lines.append(tui_loop_state.phase_gutter(phase, meta))
                lines.extend(
                    tui_loop_state.phase_card_lines(
                        self.model,
                        phase,
                        focused=phase == self.current_phase(),
                        expanded=self.expanded and phase == self.current_phase(),
                    )
                )
            lines.extend(tui_loop_state.triage_routes_lines(self.model))
            return "\n".join(lines)

        def current_phase(self) -> str:
            max_index = len(tui_loop_state.LOOP_PHASES) - 1
            self.focused_index = max(0, min(self.focused_index, max_index))
            return tui_loop_state.LOOP_PHASES[self.focused_index]

        def move(self, delta: int) -> None:
            self.focused_index = (self.focused_index + delta) % len(
                tui_loop_state.LOOP_PHASES
            )
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
            current = str(self.model.field_value(dotted, ""))
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
            current = bool(self.model.field_value(dotted, self.model.profile.pipeline.final_review))
            self.model.set_field(dotted, "false" if current else "true")
            self.rebuild()

        def rebuild(self) -> None:
            self.current_phase()
            meta = tui_loop_state.loop_rail_meta(self.model)
            self._header.update(tui_loop_state.loop_header_text(self.model))
            rail_lines = [
                tui_loop_state.phase_gutter(phase, meta)
                for phase in tui_loop_state.LOOP_PHASES
            ]
            self._rail.update("\n".join(rail_lines))
            for index, phase in enumerate(tui_loop_state.LOOP_PHASES):
                card = self._cards.get(phase)
                if card is not None:
                    card.set_state(
                        focused=index == self.focused_index,
                        expanded=self.expanded and index == self.focused_index,
                    )
            if self._routes_table is not None:
                self._routes_table.display = self.current_phase() == "triage"
                self._routes_table.rebuild()
            self.refresh()

    _LOOP_DIAGRAM_CLASS = LoopDiagram
    return _LOOP_DIAGRAM_CLASS


def _phase_enabled(model: Any, phase: str, dotted: str) -> bool:
    profile = model.profile
    if phase == "triage":
        fallback = profile.triage.enabled
    elif phase == "commit":
        fallback = profile.commit.enabled
    else:
        fallback = True
    return bool(model.field_value(dotted, fallback))
