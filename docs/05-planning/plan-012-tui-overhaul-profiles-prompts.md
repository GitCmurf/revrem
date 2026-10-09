---
document_id: REVREM-PLAN-012
type: PLAN
title: TUI Overhaul Plan 4 — Profiles Picker, Prompts Library, Route Editing
status: Draft
version: '0.6'
last_updated: '2026-06-28'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Plan 4 of the loop-first TUI overhaul (REVREM-DESIGN-001): demote profiles
  to a grouped save/load picker, add a browse/apply prompts library with harness-aware
  in-loop picking of the scalar prompt fields, and add a route-row modal that edits
  triage route cells through the working-copy model.'
keywords:
- tui
- profiles-picker
- prompts-library
- route-editing
- working-copy
- design-001
related_ids:
- REVREM-DESIGN-001
- REVREM-PLAN-010
- REVREM-PLAN-011
---

# TUI Overhaul Plan 4 — Profiles Picker, Prompts Library, Route Editing

> **For agentic workers:** Implement this plan task-by-task using the repo's normal TDD loop: write the named failing tests first, make the smallest scoped implementation, run the listed verification, then commit only the task's files. Steps use checkbox (`- [ ]`) syntax for tracking. Do not rely on external "superpowers" skills; they are not part of this repository contract.

**Goal:** Finish the overhaul's authoring surface. Demote **profiles** to a clean grouped save/load picker (yours vs presets) that loads a profile into the live loop working copy; add a **prompts** library that browses the fragment-composed prompt inventory and lets the operator pick/edit the scalar prompt fields in-loop; and add a **route-row modal** so triage's per-route cells (rendered read-only in Plan 2) become editable through the same working-copy model.

**Architecture:** Three additions on the Plan 2/3 foundation, all routed through the existing `LoopEditModel` working copy and the existing `revrem config` actions. (1) A `ProfilePicker` widget over the existing `profile_view` snapshot, grouped by source, whose load action re-points the loop's `LoopEditModel`; profile lifecycle actions reuse the existing `tui_state` shell-out plans (`new`/`clone`/`export`/`delete`/`show`/`edit`) and `import_plan_for_path(path)` for imports, while new picker view-models live in `tui_profiles_state.py`. (2) A pure `prompt_inventory()` view-model over the packaged prompt fragments + triage contracts lives in `tui_prompts_state.py`, surfaced by a browse/apply `PromptLibrary` and a harness-aware `PromptField`; a `PromptEditModal` edits the **scalar** prompt fields (`triage.prompt`, `commit.message_prompt`) into the working copy, and `g` from Loop targets one of those scalar fields before entering the Prompts workspace. (3) A `RouteEditModal` edits triage route **cells** (`triage.routes.<name>.*`) into the working copy; before route editing ships, the shared `save_profile_raw` path must materialize inherited route context the same way `set_profile_field` does, so route edits remain one explicit Save instead of immediate per-field writes.

**Tech Stack:** Python 3.12, Textual 8.2.5 (optional, lazy), `pytest` + Textual pilot, the Plan 2 `LoopEditModel` + `tui_loop_widgets` factory pattern, `prompts_composer` (`load_fragment`), and the `profiles` route edit primitives.

## Plan sequence (this is Plan 4 of 4)

1. **Plan 1 (REVREM-PLAN-009):** edit primitives — **COMPLETE.**
2. **Plan 2 (REVREM-PLAN-010):** authoring Loop screen — **prerequisite** (`LoopEditModel`, `tui_loop_widgets` factories, the read-only triage routes table this plan makes editable).
3. **Plan 3 (REVREM-PLAN-011):** live run monitor.
4. **Plan 4 (this doc):** profiles picker + prompts library + route-row editing.

> **Sequencing note:** Written against Plan 2's `LoopEditModel` (`load`, `set_field`, `is_dirty`, `save`) and the `#loop-pane` / `app._loop_diagram` / `app._loop_model` wiring. Re-confirm those exist with the documented shapes before Task 1; if Plan 2's review renamed them, revise call sites here.

## Global Constraints

Every task's requirements implicitly include this section.

- **Everything routes through the working copy + existing CLI actions.** Prompt and route edits mutate the Plan 2 `LoopEditModel` (`set_field`) and persist through the *same* `save_profile_raw` Save; profile lifecycle (new/clone/export/delete/show/edit) reuses the existing `tui_state.*_plan_for_name` shell-outs to `revrem config`, while import uses `tui_state.import_plan_for_path(path)`. No route edit may persist immediately through `set_profile_field`; if route saves need inherited-context materialization, implement it in `save_profile_raw` first.
- **Raw TOML keys (verified 2026-06-28).** Scalar prompt fields: `triage.prompt`, `commit.message_prompt`. Route cells: `triage.routes.<name>.harness`, `.model`, `.reasoning_effort`, `.timeout_seconds`, `.sandbox`, `.fallback`. Routing-level (already in Plan 2): `triage.routing.default_route`, `.strict_on_unavailable_route`, `.allow_model_escalation`. (Note: `base`/`max_iterations`/`final_review` live under `[pipeline]`, i.e. `pipeline.*` — relevant only if a modal touches them, which it does not here.)
- **Two structural limits are explicit scope cuts, not bugs.** The Plan 1 `deep_set_raw` / `save_profile_raw` primitives set a **scalar at a dict path** and **deep-merge** on write. Therefore: (a) **prompt-fragment list editing** (`triage.routing.rule[].then.prompt_fragments` is a *list*) has no working-copy save path — the `PromptLibrary` can browse assets and apply a selected asset only to targeted scalar prompt fields; fragment-list mutation and external copy actions are deferred; (b) **route deletion** cannot be expressed (merge-only write cannot remove a key) — `RouteEditModal` supports **edit existing cells + add a route**, deletion is deferred. Both are stated in the relevant tasks and the docs; do not fake them.
- **Route persistence must be made CLI-equivalent before Task 5.** Source inspection on 2026-06-28 shows `set_profile_field` has route/routing-specific inherited-context materialization, while `save_profile_raw` currently deep-merges the authored raw delta into the owner fragment. Treat route equivalence as a required failing test, not a verified premise. The chosen fix is to extend `save_profile_raw` / `write_profile_to_path` inputs so route deltas materialize the same inherited default route and fallback closure as `set_profile_field`; do **not** split route edits into immediate `set_profile_field` writes, because that would violate the Loop screen's one explicit Save model. If the spike shows this cannot be implemented locally without broad serializer redesign, stop Task 5, document the exact divergence, and ship Plan 4 as Profiles + Prompts only with route editing deferred to a follow-up plan.
- **Profiles are the save layer, not a settings editor.** The `ProfilePicker` shows identity + a one-line loop summary per row, grouped *yours* (project/user) vs *presets* (builtin); it never tries to render full settings. Builtins are loadable read-only presets. Saving a builtin-backed working copy must surface the existing clone-to-edit message from `profiles.profile_owner_path`; it must not silently write a user/project owner. Operators clone first, then edit the clone.
- **Optional Textual; config-truthful; degrade gracefully.** Same posture as Plans 2–3: lazy widget factories, `render_shell_text` fallback, guarded empties.
- **Branch & commits.** Work on `feat/tui-live-runs` (never `main`). Stage files explicitly per task — never `git add -A`. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm
  ```

## Pre-flight route-save spike for the executor

Before Task 1, run a short spike on the route-save primitive. Confirm the route-persist equivalence test fails before changing `save_profile_raw`, estimate the fix, and record the result in the Task 5 notes:

```python
from code_review_loop import profiles
# inheriting-route profile in repo A and B; then:
# save_profile_raw("p", {"triage":{"routes":{"security":{"model":"x"}}}}, cwd=A)
# set_profile_field("p", "triage.routes.security.model", "x", cwd=B)
# Expected before the prerequisite fix: these files may diverge because
# set_profile_field materializes inherited route context and save_profile_raw does not.
# Expected after the prerequisite fix: byte-identical owner files.
```

Decision gate: if the required `save_profile_raw` change is contained to route/routing materialization and can be covered by the Task 5 tests, proceed. If it requires a broad serializer rewrite or deleting/inverting inherited keys, defer route editing, keep the route table read-only, and still complete the Profiles + Prompts tasks.

---

## File structure

- **Create** `src/code_review_loop/tui_profiles_state.py` — add `profile_picker_groups`.
- **Create** `src/code_review_loop/tui_prompts_state.py` — add `prompt_inventory`, `prompt_field_label`, and prompt-target helpers.
- **Modify** `src/code_review_loop/profiles.py` — make `save_profile_raw` materialize inherited route context for route-cell deltas before route UI ships.
- **Modify** `src/code_review_loop/tui_loop_widgets.py` — add lazy factories: `profile_picker_class()`, `prompt_library_class()`, `prompt_edit_modal_class()`, `route_edit_modal_class()`.
- **Modify** `src/code_review_loop/tui.py` — mount `ProfilePicker` (Profiles workspace) and `PromptLibrary` (Prompts workspace); wire load-into-loop, prompt-target/apply, prompt-edit, and route-edit modals; bindings.
- **Create** `tests/test_tui_profiles_prompts_view.py` — pure-layer tests.
- **Modify** `tests/test_tui_pilot_smoke.py` — picker / library / modal pilot tests.
- **Modify** `docs/30-design/design-001-loop-first-tui-overhaul.md`, `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`.

---

## Task 1: Profiles picker view-model + widget (grouped save/load)

**Files:**
- Create: `src/code_review_loop/tui_profiles_state.py`
- Modify: `src/code_review_loop/tui_loop_widgets.py`, `src/code_review_loop/tui.py`
- Test: `tests/test_tui_profiles_prompts_view.py`, `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `HomeSnapshot.profiles` (`ProfileView` with `.name`, `.source`, `.base`, `.max_iterations`, `.checks`); existing `_short_source` logic; `LoopEditModel.load` (Plan 2).
- Produces:
  - `@dataclass(frozen=True) class ProfilePickerRow`: `name`, `group` (`"yours"`/`"presets"`), `source_label`, `summary`.
  - `profile_picker_groups(snapshot) -> tuple[ProfilePickerRow, ...]` (yours first, then presets; stable within group by name).
  - `profile_picker_class()` lazy widget factory; `ProfilePicker` with `rows`, `selected_index`, `move(delta)`, `selected_name()`, `rebuild()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_profiles_prompts_view.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import (
    profiles,
    tui_loop_widgets,
    tui_profiles_state,
    tui_prompts_state,
    tui_state,
)
from code_review_loop.tui_loop_model import LoopEditModel


def _snapshot(tmp_path: Path) -> tui_state.HomeSnapshot:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.dogfood]\n[profiles.dogfood.pipeline]\nbase='main'\nmax_iterations=3\n",
        encoding="utf-8",
    )
    return tui_state.build_home_snapshot(cwd=repo, home=tmp_path / "home")


def test_picker_groups_yours_before_presets(tmp_path):
    rows = tui_profiles_state.profile_picker_groups(_snapshot(tmp_path))
    assert rows  # non-empty
    groups = [r.group for r in rows]
    # all 'yours' rows come before any 'presets' row
    if "presets" in groups and "yours" in groups:
        assert groups.index("yours") < groups.index("presets")
    dogfood = next(r for r in rows if r.name == "dogfood")
    assert dogfood.group == "yours"
    assert "main" in dogfood.summary and "3" in dogfood.summary


def test_picker_classifies_builtins_as_presets(tmp_path):
    rows = tui_profiles_state.profile_picker_groups(_snapshot(tmp_path))
    builtins = [r for r in rows if r.source_label == "builtin"]
    assert builtins  # the bundled expert profiles
    assert all(r.group == "presets" for r in builtins)


def test_builtin_profile_save_is_readonly_until_cloned(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    name = next(
        item.name
        for item in profiles.list_profiles(cwd=repo, home=home, include_builtins=True)
        if item.source == profiles.BUILTIN_PROFILE_SOURCE
    )
    model = LoopEditModel.load(name, cwd=repo, home=home)
    model.set_field("review.model", "gpt-9")
    with pytest.raises(RuntimeError, match="built-in profile .* is read-only"):
        model.save()


def test_picker_empty_rows_are_safe():
    picker_cls = tui_loop_widgets.profile_picker_class()
    if picker_cls is None:
        pytest.skip("Textual is not installed")
    picker = picker_cls(())
    picker.set_rows(())
    assert picker.selected_index == 0
    assert picker.selected_name() is None
```

Append a pilot test to `tests/test_tui_pilot_smoke.py`:

```python
def test_profiles_workspace_renders_picker_and_loads_into_loop(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.dogfood]\n[profiles.dogfood.pipeline]\nbase='main'\nmax_iterations=3\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="dogfood") as (app, pilot):
            await pilot.press("3")  # Profiles workspace (Loop-first nav: 3 Profiles)
            await pilot.pause()
            picker = app.query_one("#profile-picker")
            rendered = str(picker.render())
            assert "yours" in rendered and "dogfood" in rendered

    asyncio.run(run())


def test_profile_picker_load_rebuilds_loop_diagram_for_new_profile(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.a]\n[profiles.a.pipeline]\nbase='main'\nmax_iterations=3\n"
            "[profiles.a.review]\nmodel='gpt-a'\n"
            "[profiles.b]\n[profiles.b.pipeline]\nbase='main'\nmax_iterations=9\n"
            "[profiles.b.review]\nmodel='gpt-b'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="a") as (app, pilot):
            await pilot.press("3")
            await pilot.pause()
            app._load_profile_into_loop("b")
            await pilot.pause()
            assert app._workspace == "loop"
            assert app._loop_diagram.model.name == "b"
            assert app._loop_diagram.focused_index == 0
            assert app._loop_diagram.is_dirty is False
            assert "gpt-b" in str(app.query_one("#loop-diagram").render())

    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py -q`
Expected: FAIL — `AttributeError: ... 'profile_picker_groups'`.

- [ ] **Step 3: Implement the view-model**

Create `src/code_review_loop/tui_profiles_state.py`:

```python
@dataclass(frozen=True)
class ProfilePickerRow:
    name: str
    group: str  # "yours" | "presets"
    source_label: str
    summary: str


def _picker_source_label(source: str | None) -> str:
    if not source:
        return "-"
    if source == "builtin":
        return "builtin"
    name = Path(source).name
    if name == PROJECT_CONFIG_NAME_DISPLAY:
        return "project"
    if name == "profiles.toml":
        return "user"
    return name


# Display constant mirrors profiles.PROJECT_CONFIG_NAME without importing a private.
PROJECT_CONFIG_NAME_DISPLAY = ".revrem.toml"


def profile_picker_groups(snapshot: tui_state.HomeSnapshot) -> tuple[ProfilePickerRow, ...]:
    yours: list[ProfilePickerRow] = []
    presets: list[ProfilePickerRow] = []
    for profile in snapshot.profiles:
        source_label = _picker_source_label(profile.source)
        group = "presets" if source_label == "builtin" else "yours"
        summary = (
            f"{profile.base} · {profile.max_iterations} iters · "
            f"{len(profile.checks)} checks"
        )
        row = ProfilePickerRow(
            name=profile.name, group=group, source_label=source_label, summary=summary
        )
        (presets if group == "presets" else yours).append(row)
    yours.sort(key=lambda r: r.name)
    presets.sort(key=lambda r: r.name)
    return tuple(yours) + tuple(presets)
```

- [ ] **Step 4: Implement the widget**

Append to `src/code_review_loop/tui_loop_widgets.py` (lazy-factory pattern from Plan 2):

```python
_PROFILE_PICKER_CLASS: type[Any] | None = None


def profile_picker_class() -> type[Any] | None:
    global _PROFILE_PICKER_CLASS
    from code_review_loop import tui

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if _PROFILE_PICKER_CLASS is not None:
        return _PROFILE_PICKER_CLASS

    static_cls: Any = tui._Static

    class ProfilePicker(static_cls):  # type: ignore[misc, valid-type]
        can_focus = True

        def __init__(self, rows: tuple[Any, ...], **kwargs: Any) -> None:
            super().__init__("", id=kwargs.pop("id", "profile-picker"), markup=True, **kwargs)
            self.rows = rows
            self.selected_index = 0

        def set_rows(self, rows: tuple[Any, ...]) -> None:
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

        def rebuild(self) -> None:
            lines = ["[b]PROFILES[/b]  [muted]load a saved loop[/]", ""]
            last_group = None
            for index, row in enumerate(self.rows):
                if row.group != last_group:
                    lines.append(f"[muted]─ {tui_state.markup_escape(row.group)} ─[/]")
                    last_group = row.group
                pointer = ">" if index == self.selected_index else " "
                text = (
                    f"{pointer} {tui_state.markup_escape(row.name)}  "
                    f"[muted]{tui_state.markup_escape(row.source_label)}  "
                    f"{tui_state.markup_escape(row.summary)}[/]"
                )
                lines.append(f"[status-info]{text}[/]" if index == self.selected_index else text)
            self.update("\n".join(lines))

        def on_mount(self) -> None:
            self.rebuild()

    _PROFILE_PICKER_CLASS = ProfilePicker
    return _PROFILE_PICKER_CLASS
```

- [ ] **Step 5: Mount into the Profiles workspace + load-into-loop in `tui.py`**

1. In `compose`, add a profiles pane in `#body`:

```python
                picker_cls = _profile_picker_widget(self)
                if picker_cls is not None and _Vertical is not None:
                    with _Vertical(id="profiles-pane"):
                        yield picker_cls
```

2. Add the helper near the other widget helpers:

```python
def _profile_picker_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    cls = tui_loop_widgets.profile_picker_class()
    if cls is None:
        return None
    rows = tui_profiles_state.profile_picker_groups(app.model.snapshot)
    widget = cls(rows)
    app._profile_picker = widget
    return widget
```

Initialise `self._profile_picker = None` in `__init__`.

3. Extend the `_render_workbench` display toggles so `#profiles-pane` shows on the Profiles workspace (and the legacy text panes hide on loop/run/profiles):

```python
        on_profiles = self._workspace == "profiles"
        _set_widget_display(self, "#profiles-pane", on_profiles)
        if on_profiles and self._profile_picker is not None:
            self._profile_picker.set_rows(tui_profiles_state.profile_picker_groups(self.model.snapshot))
            self._profile_picker.rebuild()
```

(and add `on_profiles` to the set of workspaces that hide `#left-pane`/`#right-pane`).

4. Route picker navigation + load. In `_move_selection`, add a branch before the Plan 2 loop branch:

```python
        if self._workspace == "profiles" and self._profile_picker is not None:
            self._profile_picker.move(delta)
            return
```

In `action_select`, when on the Profiles workspace with a picker, load the selected profile into the loop working copy:

```python
        if self._workspace == "profiles" and self._profile_picker is not None:
            name = self._profile_picker.selected_name()
            if name is not None:
                self._load_profile_into_loop(name)
            return
```

5. Add `_load_profile_into_loop` (with a dirty guard) to `_RevRemAppMixin`:

```python
    def _load_profile_into_loop(self, name: str) -> None:
        from code_review_loop import tui_loop_model

        if self._loop_diagram is not None and self._loop_diagram.is_dirty:
            _notify(self, "Unsaved loop changes — save (s on Loop) before loading another.")
            return
        try:
            model = tui_loop_model.LoopEditModel.load(name, cwd=Path(self.model.snapshot.cwd))
        except (OSError, ValueError) as exc:
            _notify(self, f"Load failed: {exc}")
            return
        self._loop_model = model
        if self._loop_diagram is not None:
            self._loop_diagram.model = model
            self._loop_diagram.focused_index = 0
            self._loop_diagram.expanded = False
            self._loop_diagram.rebuild()
        self._select_profile(name)
        self._set_workspace("loop")
        _notify(self, f"Loaded {name} into the loop.")
```

6. CSS: add `#profiles-pane { width: 1fr; height: 1fr; padding: 0 1; overflow-y: auto; }`.

- [ ] **Step 6: Run the new tests + TUI suite**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/code_review_loop/tui_profiles_state.py src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): grouped profiles picker that loads into the loop"
```

---

## Task 2: Prompts inventory view-model (pure)

A browse-only inventory of the fragment-composed prompt assets, tagged with trust/source — the data behind the library.

**Files:**
- Create: `src/code_review_loop/tui_prompts_state.py`
- Test: `tests/test_tui_profiles_prompts_view.py`

**Interfaces:**
- Consumes: the packaged `code_review_loop.prompts` resources (`fragments/*.txt`, `triage_v1.txt`, `triage_v2.txt`) via `importlib.resources`.
- Produces:
  - `@dataclass(frozen=True) class PromptAsset`: `name`, `kind` (`"fragment"`/`"contract"`), `trust` (`"builtin"`), `preview` (first ~80 chars).
  - `prompt_inventory() -> tuple[PromptAsset, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_profiles_prompts_view.py`:

```python
def test_prompt_inventory_lists_builtin_fragments_and_contracts():
    assets = tui_prompts_state.prompt_inventory()
    names = {a.name for a in assets}
    assert "security-checklist" in names
    assert any(a.kind == "contract" and a.name.startswith("triage_v") for a in assets)
    sec = next(a for a in assets if a.name == "security-checklist")
    assert sec.kind == "fragment" and sec.trust == "builtin" and sec.preview


def test_prompt_inventory_is_sorted_and_stable():
    a1 = tui_prompts_state.prompt_inventory()
    a2 = tui_prompts_state.prompt_inventory()
    assert a1 == a2
    fragment_names = [a.name for a in a1 if a.kind == "fragment"]
    assert fragment_names == sorted(fragment_names)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py -k prompt_inventory -q`
Expected: FAIL — `AttributeError: ... 'prompt_inventory'`.

- [ ] **Step 3: Implement**

Create `src/code_review_loop/tui_prompts_state.py`:

```python
@dataclass(frozen=True)
class PromptAsset:
    name: str
    kind: str  # "fragment" | "contract"
    trust: str
    preview: str


def _preview_of(text: str, *, limit: int = 80) -> str:
    flattened = " ".join(text.split())
    return flattened[:limit]


def prompt_inventory() -> tuple[PromptAsset, ...]:
    from importlib.resources import files as _files

    root = _files("code_review_loop.prompts")
    fragments: list[PromptAsset] = []
    frag_dir = root.joinpath("fragments")
    for entry in sorted(p.name for p in frag_dir.iterdir() if p.name.endswith(".txt")):
        name = entry[: -len(".txt")]
        text = frag_dir.joinpath(entry).read_text(encoding="utf-8")
        fragments.append(
            PromptAsset(name=name, kind="fragment", trust="builtin", preview=_preview_of(text))
        )
    contracts: list[PromptAsset] = []
    for entry in sorted(p.name for p in root.iterdir() if p.name.startswith("triage_v")):
        name = entry[: -len(".txt")] if entry.endswith(".txt") else entry
        text = root.joinpath(entry).read_text(encoding="utf-8")
        contracts.append(
            PromptAsset(name=name, kind="contract", trust="builtin", preview=_preview_of(text))
        )
    return tuple(fragments) + tuple(contracts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py -k prompt_inventory -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_prompts_state.py tests/test_tui_profiles_prompts_view.py
git commit -m "feat(tui): prompt inventory view-model"
```

---

## Task 3: Prompts library widget + harness-aware prompt field label

**Files:**
- Modify: `src/code_review_loop/tui_prompts_state.py`, `src/code_review_loop/tui_loop_widgets.py`, `src/code_review_loop/tui.py`
- Test: `tests/test_tui_profiles_prompts_view.py`, `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `prompt_inventory` (Task 2); `harnesses` review capability; the loop's `LoopEditModel` for the scalar prompt field values.
- Produces:
  - `prompt_field_label(phase, harness, value) -> str` — harness-aware (codex review → `built-in review (codex)`; otherwise the field value or `<default>`).
  - `prompt_library_class()` lazy widget; `PromptLibrary` browse list with `move`, `selected_asset()`, `rebuild`. The widget is browse-only unless `app._prompt_target_key` is set by Loop's `g` action; in that targeted mode `Enter` applies the selected asset content into the scalar prompt field and returns to Loop.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_profiles_prompts_view.py`:

```python
def test_prompt_field_label_codex_review_is_builtin():
    assert tui_prompts_state.prompt_field_label("review", "codex", None) == "built-in review (codex)"


def test_prompt_field_label_external_shows_value_or_default():
    assert tui_prompts_state.prompt_field_label("triage", "claude", None) == "<default>"
    assert tui_prompts_state.prompt_field_label("triage", "claude", "Focus on docs drift") == (
        "Focus on docs drift"
    )


def test_prompt_field_label_triage_codex_uses_scalar_value_or_default():
    assert tui_prompts_state.prompt_field_label("triage", "codex", None) == "<default>"
    assert tui_prompts_state.prompt_field_label("triage", "codex", "Route carefully") == (
        "Route carefully"
    )
```

Append a pilot test to `tests/test_tui_pilot_smoke.py`:

```python
def test_prompts_workspace_renders_library(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("4")  # Prompts workspace (Loop-first nav: 4 Prompts)
            await pilot.pause()
            library = app.query_one("#prompt-library")
            assert "security-checklist" in str(library.render())

    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py -k prompt_field_label -q`
Expected: FAIL — `AttributeError: ... 'prompt_field_label'`.

- [ ] **Step 3: Implement the label helper**

Append to `src/code_review_loop/tui_prompts_state.py`:

```python
def prompt_field_label(phase: str, harness: str | None, value: str | None) -> str:
    if phase == "review" and harness == "codex":
        return "built-in review (codex)"
    if value:
        return value
    return "<default>"
```

- [ ] **Step 4: Implement the `PromptLibrary` widget**

Append to `src/code_review_loop/tui_loop_widgets.py` (lazy factory). It displays asset name, kind, trust, and preview. It must not claim or attempt external copy integration. Fragment-list insertion into a route is deferred (see Global Constraints):

```python
_PROMPT_LIBRARY_CLASS: type[Any] | None = None


def prompt_library_class() -> type[Any] | None:
    global _PROMPT_LIBRARY_CLASS
    from code_review_loop import tui

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if _PROMPT_LIBRARY_CLASS is not None:
        return _PROMPT_LIBRARY_CLASS

    static_cls: Any = tui._Static

    class PromptLibrary(static_cls):  # type: ignore[misc, valid-type]
        can_focus = True

        def __init__(self, **kwargs: Any) -> None:
            super().__init__("", id=kwargs.pop("id", "prompt-library"), markup=True, **kwargs)
            self.assets = tui_prompts_state.prompt_inventory()
            self.selected_index = 0

        def move(self, delta: int) -> None:
            if self.assets:
                self.selected_index = (self.selected_index + delta) % len(self.assets)
                self.rebuild()

        def selected_asset(self) -> Any | None:
            return self.assets[self.selected_index] if self.assets else None

        def rebuild(self) -> None:
            lines = ["[b]PROMPTS[/b]  [muted]library (browse)[/]", ""]
            for index, asset in enumerate(self.assets):
                pointer = ">" if index == self.selected_index else " "
                text = (
                    f"{pointer} {tui_state.markup_escape(asset.name)}  "
                    f"[muted]{tui_state.markup_escape(asset.kind)} · "
                    f"{tui_state.markup_escape(asset.trust)}[/]"
                )
                lines.append(f"[status-info]{text}[/]" if index == self.selected_index else text)
            asset = self.selected_asset()
            if asset is not None:
                lines.extend(("", f"[muted]{tui_state.markup_escape(asset.preview)}[/]"))
            self.update("\n".join(lines))

        def on_mount(self) -> None:
            self.rebuild()

    _PROMPT_LIBRARY_CLASS = PromptLibrary
    return _PROMPT_LIBRARY_CLASS
```

- [ ] **Step 5: Mount into the Prompts workspace + apply targeted prompts in `tui.py`**

Mirror Task 1's profiles-pane mounting: a `_prompt_library_widget(app)` helper that builds the widget and stores `app._prompt_library`; a `#prompts-pane` `_Vertical` in `compose`; display-toggle in `_render_workbench` (`on_prompts = self._workspace == "prompts"`); navigation delegation in `_move_selection`; CSS `#prompts-pane { width: 1fr; height: 1fr; padding: 0 1; overflow-y: auto; }`. Initialise `self._prompt_library = None`, `self._prompt_target_key = None`, and `self._prompt_return_workspace = None` in `__init__`.

Add Loop key `g` → `action_goto_prompts`. When the Loop focus is on `triage` or `commit`, set `_prompt_target_key` to `triage.prompt` or `commit.message_prompt`, remember the return workspace as `"loop"`, switch to the Prompts workspace, and notify `Select a prompt asset, Enter to apply`. If the focused phase has no scalar prompt field, notify and stay in Loop.

In `action_select`, when on the Prompts workspace and `_prompt_target_key` is set, read `self._prompt_library.selected_asset()`, load its full text from the packaged prompt resource by asset kind/name, call `_apply_prompt_edit(self._prompt_target_key, text)`, clear `_prompt_target_key`, switch back to Loop, and rebuild the diagram. If no target is set, `Enter` only shows a browse status message and does not mutate the working copy.

Add a pilot test:

```python
def test_loop_goto_prompts_applies_selected_asset_to_scalar_prompt(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 1  # triage
            await pilot.press("g")
            await pilot.pause()
            assert app._workspace == "prompts"
            app._prompt_library.selected_index = 0
            await pilot.press("enter")
            await pilot.pause()
            assert app._workspace == "loop"
            assert diagram.model.field_value("triage.prompt", None)
            assert diagram.is_dirty is True

    asyncio.run(run())
```

- [ ] **Step 6: Run tests + TUI suite**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/code_review_loop/tui_prompts_state.py src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): prompts library browse + harness-aware prompt label"
```

---

## Task 4: Prompt-edit modal (scalar prompt fields → working copy)

A focused modal that edits the scalar prompt fields `triage.prompt` and `commit.message_prompt` into the loop working copy. Reuses the existing `TextPrompt` modal infrastructure.

**Files:**
- Modify: `src/code_review_loop/tui.py`
- Test: `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `LoopEditModel.set_field` (Plan 2); the existing `text_prompt_screen_class()` modal (`tui.py`); the loop's currently-focused phase.
- Produces: `action_edit_prompt` on the app, bound to `e` on the Loop workspace.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tui_pilot_smoke.py`:

```python
def test_prompt_edit_sets_scalar_field_on_working_copy(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.commit]\nenabled=true\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")  # Loop
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            # focus the commit phase (index 4) and apply a prompt edit directly
            diagram.focused_index = 4
            app._apply_prompt_edit("commit.message_prompt", "Use imperative subject lines")
            await pilot.pause()
            assert diagram.model.field_value("commit.message_prompt", None) == (
                "Use imperative subject lines"
            )
            assert diagram.is_dirty is True

    asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k prompt_edit_sets_scalar -q`
Expected: FAIL — `_apply_prompt_edit` not defined.

- [ ] **Step 3: Implement**

In `src/code_review_loop/tui.py`:

1. Map the focused loop phase to its scalar prompt key:

```python
_PROMPT_FIELD_BY_PHASE = {
    "triage": "triage.prompt",
    "commit": "commit.message_prompt",
}
```

2. Add the action + apply helper to `_RevRemAppMixin`:

```python
    def action_edit_prompt(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            return
        phase = self._loop_diagram.current_phase()
        key = _PROMPT_FIELD_BY_PHASE.get(phase)
        if key is None:
            _notify(self, f"{phase} has no editable prompt field (codex review is built-in).")
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
        _notify(self, f"Set {key} (unsaved — s to save).")
```

3. Bind `e` to `action_edit_prompt` in `_build_bindings` (the Loop workspace; on other workspaces `e` keeps `edit_profile` — dispatch by workspace inside `action_edit_prompt` by falling back to `self.action_edit_profile()` when not on the loop, mirroring how Plan 2 dispatched `s`).

- [ ] **Step 4: Run test + suite**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): edit scalar prompt fields into the loop working copy"
```

---

## Task 5: Route-edit modal (route cells → working copy; add route)

Make the Plan 2 read-only triage routes table editable: edit a route's cells and add a new route, both through the working copy. **Route deletion is deferred** (the merge-only `save_profile_raw` cannot remove a key).

**Files:**
- Modify: `src/code_review_loop/tui_loop_widgets.py`, `src/code_review_loop/tui.py`
- Modify: `src/code_review_loop/profiles.py` (route materialization in `save_profile_raw`, before widget work)
- Test: `tests/test_tui_pilot_smoke.py`, `tests/test_tui_loop_model.py`

**Interfaces:**
- Consumes: `LoopEditModel.set_field`/`save`; the loop's triage routes (`profile.triage.routes`); `HARNESS_CHOICES`/`EFFORT_CHOICES` (Plan 2); `profiles.set_profile_field` (only as the byte-equivalence oracle for the shared save primitive).
- Produces: `route_edit_modal_class()` (a `ModalScreen` with per-cell inputs); `action_edit_route` + `action_add_route` on the app, bound on the Loop workspace when triage is focused.

- [ ] **Step 0: Fix the shared route-save primitive before UI work**

Append to `tests/test_tui_loop_model.py` (locks the architectural requirement that route edits remain in the working copy and persist through one Save):

```python
def test_route_cell_edit_save_materializes_inherited_route_like_config_set(tmp_path):
    body = "\n".join(
        (
            "[defaults.triage.routing]",
            "enabled=true",
            "default_route='security'",
            "[defaults.triage.routes.security]",
            "harness='codex'",
            "model='gpt-5.4'",
            "reasoning_effort='high'",
            "sandbox='read-only'",
            "[profiles.p]",
            "[profiles.p.pipeline]",
            "base='main'",
            "[profiles.p.triage]",
            "enabled=true",
        )
    )
    repo_model = tmp_path / "via_model" / "r"
    repo_set = tmp_path / "via_set" / "r"
    for repo in (repo_model, repo_set):
        (repo / ".git").mkdir(parents=True)
        (repo / ".revrem.toml").write_text(body + "\n", encoding="utf-8")

    model = LoopEditModel.load("p", cwd=repo_model)
    model.set_field("triage.routes.security.model", "gpt-9")
    model.save()
    profiles.set_profile_field("p", "triage.routes.security.model", "gpt-9", cwd=repo_set)

    assert (repo_model / ".revrem.toml").read_text(encoding="utf-8") == (
        repo_set / ".revrem.toml"
    ).read_text(encoding="utf-8")


def test_route_cell_edit_save_materializes_fallback_closure(tmp_path):
    body = "\n".join(
        (
            "[defaults.triage.routing]",
            "enabled=true",
            "default_route='foo'",
            "[defaults.triage.routes.foo]",
            "harness='codex'",
            "fallback='bar'",
            "sandbox='read-only'",
            "[defaults.triage.routes.bar]",
            "harness='codex'",
            "sandbox='workspace-write'",
            "[profiles.p]",
            "[profiles.p.pipeline]",
            "base='main'",
            "[profiles.p.triage]",
            "enabled=true",
        )
    )
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(body + "\n", encoding="utf-8")

    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.foo.model", "gpt-9")
    model.save()

    reloaded = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert reloaded.triage.routes["foo"].fallback == "bar"
    assert "bar" in reloaded.triage.routes
```

Run: `python -m pytest tests/test_tui_loop_model.py -k "route_cell_edit_save" -q`
Expected before implementation: FAIL — the saved owner file lacks the inherited route rows/materialized fallback closure. Implement inherited route materialization in `save_profile_raw` so the tests pass. Do not route the TUI Save path through per-field `set_profile_field`.

- [ ] **Step 1: Write the failing UI tests**

Append a pilot test to `tests/test_tui_pilot_smoke.py`:

```python
def test_route_edit_updates_working_copy(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        repo.joinpath(".revrem.toml").write_text(
            "\n".join(
                (
                    "[profiles.p]",
                    "[profiles.p.pipeline]",
                    "base='main'",
                    "[profiles.p.triage]",
                    "enabled=true",
                    "contract='v2'",
                    "[profiles.p.triage.routing]",
                    "enabled=true",
                    "default_route='security'",
                    "[profiles.p.triage.routes.security]",
                    "harness='codex'",
                    "model='gpt-5.4'",
                    "sandbox='read-only'",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="p") as (app, pilot):
            await pilot.press("1")  # Loop
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 1  # triage
            app._apply_route_edit("security", "model", "gpt-9")
            await pilot.pause()
            assert diagram.model.field_value(
                "triage.routes.security.model", None
            ) == "gpt-9"
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_route_add_creates_saveable_route_with_explicit_defaults(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "\n".join(
            (
                "[profiles.p]",
                "[profiles.p.pipeline]",
                "base='main'",
                "[profiles.p.triage]",
                "enabled=true",
                "contract='v2'",
                "[profiles.p.triage.routing]",
                "enabled=true",
                "default_route='security'",
                "[profiles.p.triage.routes.security]",
                "harness='codex'",
                "sandbox='read-only'",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.audit.harness", "codex")
    model.set_field("triage.routes.audit.sandbox", "workspace-write")
    model.save()
    reloaded = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert reloaded.triage.routes["audit"].harness == "codex"
    assert reloaded.triage.routes["audit"].sandbox == "workspace-write"


def test_route_add_from_disabled_routing_enables_v2_context(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n[profiles.p.triage]\nenabled=true\n",
        encoding="utf-8",
    )
    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.contract", "v2")
    model.set_field("triage.routing.enabled", "true")
    model.set_field("triage.routing.default_route", "audit")
    model.set_field("triage.routes.audit.harness", "codex")
    model.set_field("triage.routes.audit.sandbox", "workspace-write")
    model.save()
    reloaded = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert reloaded.triage.contract == "v2"
    assert reloaded.triage.routing.enabled is True
    assert reloaded.triage.routing.default_route == "audit"
    assert reloaded.triage.routes["audit"].harness == "codex"


def test_route_add_rejects_invalid_and_duplicate_names(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        repo.joinpath(".revrem.toml").write_text(
            "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
            "[profiles.p.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.p.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.p.triage.routes.security]\nharness='codex'\nsandbox='read-only'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="p") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 1  # triage
            app._apply_route_add("bad.name")
            app._apply_route_add("security")
            assert diagram.is_dirty is False
            app._apply_route_add("audit")
            assert diagram.model.field_value("triage.routes.audit.harness", None) == "codex"
            assert diagram.model.field_value(
                "triage.routes.audit.sandbox", None
            ) == "workspace-write"
            assert diagram.is_dirty is True

    asyncio.run(run())
```

- [ ] **Step 2: Run UI tests to verify they fail**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k route_edit -q`
Expected: FAIL — `_apply_route_edit` not defined.

- [ ] **Step 3: Implement the route-edit apply path + modal**

In `src/code_review_loop/tui.py`, import `re` near the other standard-library imports and add the apply helpers (the modal is a UI affordance over these; the helpers are what the tests and the modal both call):

```python
    def _apply_route_edit(self, route: str, cell: str, value: str) -> None:
        if self._loop_diagram is None:
            return
        key = f"triage.routes.{route}.{cell}"
        try:
            self._loop_diagram.model.set_field(key, value)
        except ValueError as exc:
            _notify(self, f"Invalid {cell}: {exc}")
            return
        self._loop_diagram.rebuild()
        self._update_console_status()
        _notify(self, f"Set {key} (unsaved — s to save).")

    _ROUTE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

    def _apply_route_add(self, route: str) -> None:
        if self._loop_diagram is None:
            return
        route = route.strip()
        if not route or "." in route or _ROUTE_NAME_RE.fullmatch(route) is None:
            _notify(self, "Invalid route name: use letters, numbers, '-' or '_'.")
            return
        route_harness_key = f"triage.routes.{route}.harness"
        if (
            route in self._loop_diagram.model.profile.triage.routes
            or self._loop_diagram.model.field_value(route_harness_key, None) is not None
        ):
            _notify(self, f"Route already exists: {route}")
            return
        self._loop_diagram.model.set_field(route_harness_key, "codex")
        self._loop_diagram.model.set_field(
            f"triage.routes.{route}.sandbox", "workspace-write"
        )
        if not self._loop_diagram.model.profile.triage.routing.enabled:
            self._loop_diagram.model.set_field("triage.contract", "v2")
            self._loop_diagram.model.set_field("triage.routing.enabled", "true")
            self._loop_diagram.model.set_field("triage.routing.default_route", route)
        self._loop_diagram.rebuild()
        self._update_console_status()
        _notify(self, f"Added route {route} (unsaved — s to save).")

    def action_add_route(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            return
        if self._loop_diagram.current_phase() != "triage":
            _notify(self, "Add route: focus the triage phase first.")
            return
        self._prompt_for_text(
            title="Add route",
            prompt="New route name",
            initial="",
            on_submit=self._apply_route_add,
        )
```

Add the `route_edit_modal_class()` factory to `src/code_review_loop/tui_loop_widgets.py` — a `ModalScreen` (mirror `tui.text_prompt_screen_class`) with a concrete layout:

- Header: `Route: <name>` and a one-line status hint.
- One row per scalar cell: `harness`, `model`, `reasoning_effort`, `timeout_seconds`, `sandbox`, `fallback`.
- `harness` cycles through Plan 2 `HARNESS_CHOICES`; `reasoning_effort` cycles through Plan 2 `EFFORT_CHOICES`; `fallback` cycles through existing route names plus a blank/no-fallback option; `model`, `timeout_seconds`, and `sandbox` use text inputs.
- `Tab` / `Shift+Tab` moves between rows; `Enter` submits the focused cell; `Esc` cancels.
- Submission calls the callback with `(route, cell, value)`.

Bind `a` → `action_add_route` on the Loop workspace; the route-edit modal opens from the triage-focused card on `Enter` (extend Plan 2's `action_select`/expand handling to detect a selected triage-route row). If the selected row is the routing metadata row rather than a route row, `Enter` expands/collapses instead of opening the modal.

**Deferred (stated, not built):** route **deletion** (`x remove` in the design mockup) — the working-copy `save_profile_raw` is merge-only and cannot remove a route key; this needs a delete-capable primitive (future plan). The route-edit modal must not offer a remove action that silently no-ops. Task 6 updates REVREM-DESIGN-001 §5.1 so the design no longer advertises `x remove` as shipped in this slice.

- [ ] **Step 4: Run tests + full suite**

Run: `python -m pytest tests/test_tui_loop_model.py tests/test_tui_pilot_smoke.py -q && ./scripts/dev-check`
Expected: PASS repo-wide.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/profiles.py src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py tests/test_tui_loop_model.py
git commit -m "feat(tui): edit triage route cells + add route via working copy"
```

---

## Task 6: Documentation + changelog + final verification

**Files:**
- Modify: `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`

- [ ] **Step 1: Document profiles, prompts, and route editing**

In `docs/70-devex/devex-001-using-code-review-loop.md`, update the replacement TUI section introduced by Plan 010; do not add conflicting subsections. Cover: the **Profiles** workspace (grouped picker; `Enter` loads a saved loop into the editor; lifecycle actions still shell through `revrem config`; builtins are read-only presets and must be cloned before saving edits); the **Prompts** library (browse fragments + triage contracts; **fragment-list editing is not yet available** — pick scalar prompt fields in-loop with `e`, or press `g` from a triage/commit phase to target a scalar prompt field, choose a prompt asset with `Enter`, and return to Loop); **route editing** from the triage phase (`Enter` to edit a route's cells, `a` to add a route; **route deletion is not yet available**).

In `docs/30-design/design-001-loop-first-tui-overhaul.md`, reconcile §5.1 with the implemented slice:

- Replace the route footer `↵ edit route · a add · x remove` with `↵ edit route · a add`.
- Replace the interaction bullet "`a`/`x` add/remove" with "`a` adds; route deletion is deferred until a delete-capable profile-save primitive exists."
- Add the same limitation to §9 Open questions / future so a future executor sees that route deletion is a known deferred capability, not an accidental omission.

- [ ] **Step 2: CHANGELOG entry**

Under Unreleased → Added:

```
- TUI: profiles workspace is now a grouped save/load picker that loads a profile
  into the live loop editor; a prompts library lists fragment-composed assets and
  can apply a selected asset to targeted scalar prompt fields; triage route cells
  and scalar prompt fields (triage.prompt, commit.message_prompt) are editable
  in-loop through the working copy.
```

Under Unreleased → Notes (or Known limitations), state the two deferred items:

```
- TUI route deletion and prompt-fragment list editing are deferred (the current
  profile-save primitive is merge-only / scalar-only).
```

- [ ] **Step 3: Final cross-plan integration + full-suite gate**

Add a final cross-plan pilot test before the full gate:

```python
def test_picker_loaded_profile_edit_save_run_matches_live_diagram(tmp_path, monkeypatch):
    from support.git_fixtures import init_repo

    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, profile_name="a", review_model="slow_cancel", artifact_dir="runs/a")
        _write_live_profile(repo, profile_name="b", review_model="slow_cancel", artifact_dir="runs/b")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        async with pilot_app(cwd=repo, profile_name="a") as (app, pilot):
            await pilot.press("3")
            await pilot.pause()
            app._load_profile_into_loop("b")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_loop_meta_field("max_iterations", "4")
            app.action_save_loop()
            await pilot.press("r")
            await pilot.press("r")
            await _wait_for(
                lambda: app._workspace == "run" and app._loop_run_view is not None,
                pilot_pause=pilot.pause,
            )
            rendered = _render(app, "#loop-run")
            assert "b" in rendered
            assert "4" in rendered
            app.live_run_controller.cancel(grace_seconds=1)

    asyncio.run(run())
```

Run: `./scripts/dev-check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/30-design/design-001-loop-first-tui-overhaul.md docs/70-devex/devex-001-using-code-review-loop.md CHANGELOG.md
git commit -m "docs(tui): document profiles picker, prompts library, route editing"
```

---

## Integration Appendix: final app shape and keymap

Before final review, consolidate the three-plan edits across the integration-heavy surfaces. This appendix is the executor's checklist; if implementation names differ, update this section in the same commit that changes them.

**`__init__` final attributes:**

```python
self._loop_model = None
self._loop_diagram = None
self._loop_run_view = None
self._event_log = None
self._profile_picker = None
self._prompt_library = None
self._prompt_target_key = None
self._prompt_return_workspace = None
self._workspace = "loop"
```

**`compose` final panes:**

- `#loop-pane` contains the `LoopDiagram`.
- `#run-pane` contains `LoopRunView` plus `EventLog`.
- `#profiles-pane` contains `ProfilePicker`.
- `#prompts-pane` contains `PromptLibrary`.
- Existing legacy `#left-pane` / `#right-pane` remain available for fallback/detail content but are hidden on the dedicated Loop/Run/Profiles/Prompts workspaces as documented by each plan.

**`_render_workbench` final visibility rule:**

```python
on_loop = self._workspace == "loop"
on_run = self._workspace == "run"
on_profiles = self._workspace == "profiles"
on_prompts = self._workspace == "prompts"
```

Show exactly one dedicated workspace pane for those four booleans. Hide the legacy text panes on all four dedicated workspaces unless a Textual factory returned `None`, in which case fall back to the existing text render.

**`_build_bindings` final workspace keys:**

| Key | Workspace | Primary actions |
| --- | --- | --- |
| `1` | Loop | author/edit loop |
| `2` | Run | live monitor |
| `3` | Profiles | grouped save/load picker |
| `4` | Prompts | browse prompt assets |

**Context keys by workspace:**

| Workspace | Keys |
| --- | --- |
| Loop | `space` toggle enabled, `Enter` expand/edit or route modal, `m` harness, `f` effort, `M` model, `t` timeout, `i` max iterations, `F` final review, `e` scalar prompt edit, `g` choose prompt asset for focused triage/commit prompt, `a` add route when triage focused, `s` save, `r` save-and-run/run |
| Run | `k` stop/cancel, `l` toggle event/log tail, `o` show artifacts directory |
| Profiles | `Enter` load profile into Loop, existing lifecycle keys continue to shell through `revrem config` |
| Prompts | navigate prompt inventory; `Enter` applies to the targeted scalar prompt field only when entered via Loop `g`; no copy/fragment mutation action |

**Footer/devex requirement:** Task 6 must publish the same per-workspace key table in `docs/70-devex/devex-001-using-code-review-loop.md` so the showcase has one user-facing source of truth.

---

## Self-review (run by the plan author before execution)

**Spec coverage (REVREM-DESIGN-001 §5.3, §5.4, §6, and §5.1 route editing):**
- Profiles demoted to a grouped save/load picker (yours vs presets), load-into-loop → Task 1. ✓
- Lifecycle actions still shell through `revrem config` → reused `tui_state.*_plan_for_name` (unchanged). ✓
- Prompts library (browse surface) + in-loop picking → Tasks 2–4; targeted scalar-field apply via Loop `g` is covered; fragment-list curation **reserved/deferred** with stated reason (matches §5.4 "library surface + in-loop picking; advanced curation reserved"). ✓
- Harness-aware prompt field (codex review built-in; triage/codex scalar labels included) → `prompt_field_label` (Task 3). ✓
- Triage route-row editing and route creation (the Plan 2 read-only table) → `RouteEditModal` + `_apply_route_edit` + `_apply_route_add` (Task 5); deletion deferred with stated reason. New routes validate names and write explicit `harness="codex"` / `sandbox="workspace-write"` defaults without inventing model or reasoning-effort values. ✓
- All edits flow through the working copy + explicit Save → `LoopEditModel.set_field`/`save`; Task 5 first fixes and locks route inherited-context materialization in `save_profile_raw`, then route UI tests rely on that shared path. ✓

**Honesty about limits (a reviewer rewards this):** two structurally-identical merge-only/scalar-only gaps (route deletion; fragment-list editing) are both deferred with the *same* root-cause explanation and surfaced in the docs — not one handled and one quietly promised. External copy actions are also deliberately absent from the prompt library in this plan; `Enter` applies only to an explicit scalar prompt target set by Loop `g`.

**Placeholder scan:** none — every code/test step shows complete content, including Task 5's `route_edit_modal_class` layout contract (one row per scalar route cell, cycle widgets for harness/effort, text inputs for scalar free-text cells, callback `(route, cell, value)`). If the executor wants a failing test for the modal's compose, add one asserting the modal yields one input/control per route cell.

**Type consistency:** `tui_profiles_state.profile_picker_groups`/`ProfilePickerRow`, `tui_prompts_state.prompt_inventory`/`PromptAsset`, `prompt_field_label`, and the widget factories `profile_picker_class`/`prompt_library_class`/`route_edit_modal_class` match between definition and `tui.py` use. Raw keys (`triage.prompt`, `commit.message_prompt`, `triage.routes.<name>.<cell>`) match the verified schema. `LoopEditModel.set_field`/`field_value`/`save` calls match Plan 2's signatures.

**Prompt-library guard scan:** before final review, run `rg -n 'copy-name|clipboard|copies its name|copy_to_clipboard' docs/05-planning/plan-012-tui-overhaul-profiles-prompts.md`. Hits are allowed only in this guard/self-review section; the implemented PromptLibrary has targeted scalar-field apply only and no external copy action.

**Dependency on Plans 2–3:** reuses `LoopEditModel`, `HARNESS_CHOICES`/`EFFORT_CHOICES`, the `#loop-pane`/`app._loop_diagram` wiring, the display-toggle layout, and the `tui_loop_widgets` lazy-factory + `TextPrompt` modal patterns. Flagged in the sequencing note; re-confirm before Task 1.
