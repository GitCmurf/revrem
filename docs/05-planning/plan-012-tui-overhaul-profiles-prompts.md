---
document_id: REVREM-PLAN-012
type: PLAN
title: TUI Overhaul Plan 4 — Profiles Picker, Prompts Library, Route Editing
status: Draft
version: '0.1'
last_updated: '2026-06-28'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Plan 4 of the loop-first TUI overhaul (REVREM-DESIGN-001): demote profiles
  to a grouped save/load picker, add a browse-only prompts library with harness-aware
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

**Architecture:** Three additions on the Plan 2/3 foundation, all routed through the existing `LoopEditModel` working copy and the existing `revrem config` actions. (1) A `ProfilePicker` widget over the existing `profile_view` snapshot, grouped by source, whose load action re-points the loop's `LoopEditModel`; profile lifecycle (new/clone/export/delete/import) reuses the `tui_state` `*_plan_for_name` shell-outs unchanged. (2) A pure `prompt_inventory()` view-model over the packaged prompt fragments + triage contracts, surfaced by a browse-only `PromptLibrary` and a harness-aware `PromptField`; a `PromptEditModal` edits the **scalar** prompt fields (`triage.prompt`, `commit.message_prompt`) into the working copy. (3) A `RouteEditModal` edits triage route **cells** (`triage.routes.<name>.*`) into the working copy; the verified-equivalent `save_profile_raw` persist path keeps route edits CLI-equivalent.

**Tech Stack:** Python 3.12, Textual 8.2.5 (optional, lazy), `pytest` + Textual pilot, the Plan 2 `LoopEditModel` + `tui_loop_widgets` factory pattern, `prompts_composer` (`load_fragment`), and the `profiles` route edit primitives.

## Plan sequence (this is Plan 4 of 4)

1. **Plan 1 (REVREM-PLAN-009):** edit primitives — **COMPLETE.**
2. **Plan 2 (REVREM-PLAN-010):** authoring Loop screen — **prerequisite** (`LoopEditModel`, `tui_loop_widgets` factories, the read-only triage routes table this plan makes editable).
3. **Plan 3 (REVREM-PLAN-011):** live run monitor.
4. **Plan 4 (this doc):** profiles picker + prompts library + route-row editing.

> **Sequencing note:** Written against Plan 2's `LoopEditModel` (`load`, `set_field`, `is_dirty`, `save`) and the `#loop-pane` / `app._loop_diagram` / `app._loop_model` wiring. Re-confirm those exist with the documented shapes before Task 1; if Plan 2's review renamed them, revise call sites here.

## Global Constraints

Every task's requirements implicitly include this section.

- **Everything routes through the working copy + existing CLI actions.** Prompt and route edits mutate the Plan 2 `LoopEditModel` (`set_field`) and persist through the *same* `save_profile_raw` Save; profile lifecycle (new/clone/export/delete/import/show/edit) reuses the existing `tui_state.*_plan_for_name` shell-outs to `revrem config`. No new persistence primitive is introduced.
- **Raw TOML keys (verified 2026-06-28).** Scalar prompt fields: `triage.prompt`, `commit.message_prompt`. Route cells: `triage.routes.<name>.harness`, `.model`, `.reasoning_effort`, `.timeout_seconds`, `.sandbox`, `.fallback`. Routing-level (already in Plan 2): `triage.routing.default_route`, `.strict_on_unavailable_route`, `.allow_model_escalation`. (Note: `base`/`max_iterations`/`final_review` live under `[pipeline]`, i.e. `pipeline.*` — relevant only if a modal touches them, which it does not here.)
- **Two structural limits are explicit scope cuts, not bugs.** The Plan 1 `deep_set_raw` / `save_profile_raw` primitives set a **scalar at a dict path** and **deep-merge** on write. Therefore: (a) **prompt-fragment list editing** (`triage.routing.rule[].then.prompt_fragments` is a *list*) has no working-copy save path — the `PromptLibrary` is **browse + copy-name only**, fragment-list mutation is deferred; (b) **route deletion** cannot be expressed (merge-only write cannot remove a key) — `RouteEditModal` supports **edit existing cells + add a route**, deletion is deferred. Both are stated in the relevant tasks and the docs; do not fake them.
- **Route persistence is CLI-equivalent (verified).** For an inheriting profile, `save_profile_raw("p", {"triage":{"routes":{R:{...}}}})` produced a byte-identical owner file to `set_profile_field("p","triage.routes.R....", ...)` on 2026-06-28. Task 5 locks this with a round-trip test; if a future fallback-closure case diverges, fall back to per-field `set_profile_field` for routes (documented in Task 5).
- **Profiles are the save layer, not a settings editor.** The `ProfilePicker` shows identity + a one-line loop summary per row, grouped *yours* (project/user) vs *presets* (builtin); it never tries to render full settings. Builtins are clone-to-edit (loadable, but Save writes to a non-builtin owner via the existing `save_profile_raw` owner resolution).
- **Optional Textual; config-truthful; degrade gracefully.** Same posture as Plans 2–3: lazy widget factories, `render_shell_text` fallback, guarded empties.
- **Branch & commits.** Work on `feat/tui-live-runs` (never `main`). Stage files explicitly per task — never `git add -A`. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm
  ```

## Pre-flight check for the executor

Re-confirm the route-persist equivalence still holds before Task 5 (it gates whether route edits may use the working-copy path):

```python
from code_review_loop import profiles
# inheriting-route profile in repo A and B; then:
# save_profile_raw("p", {"triage":{"routes":{"security":{"model":"x"}}}}, cwd=A)
# set_profile_field("p", "triage.routes.security.model", "x", cwd=B)
# assert (A/".revrem.toml").read_text() == (B/".revrem.toml").read_text()
```

---

## File structure

- **Modify** `src/code_review_loop/tui_state.py` — add `profile_picker_groups`, `prompt_inventory`, `prompt_field_label`.
- **Modify** `src/code_review_loop/tui_loop_widgets.py` — add lazy factories: `profile_picker_class()`, `prompt_library_class()`, `prompt_edit_modal_class()`, `route_edit_modal_class()`.
- **Modify** `src/code_review_loop/tui.py` — mount `ProfilePicker` (Profiles workspace) and `PromptLibrary` (Prompts workspace); wire load-into-loop, prompt-edit, and route-edit modals; bindings.
- **Create** `tests/test_tui_profiles_prompts_view.py` — pure-layer tests.
- **Modify** `tests/test_tui_pilot_smoke.py` — picker / library / modal pilot tests.
- **Modify** `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`.

---

## Task 1: Profiles picker view-model + widget (grouped save/load)

**Files:**
- Modify: `src/code_review_loop/tui_state.py`, `src/code_review_loop/tui_loop_widgets.py`, `src/code_review_loop/tui.py`
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

from code_review_loop import profiles, tui_state


def _snapshot(tmp_path: Path) -> tui_state.HomeSnapshot:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.dogfood]\n[profiles.dogfood.pipeline]\nbase='main'\nmax_iterations=3\n",
        encoding="utf-8",
    )
    return tui_state.build_home_snapshot(cwd=repo, home=tmp_path / "home")


def test_picker_groups_yours_before_presets(tmp_path):
    rows = tui_state.profile_picker_groups(_snapshot(tmp_path))
    assert rows  # non-empty
    groups = [r.group for r in rows]
    # all 'yours' rows come before any 'presets' row
    if "presets" in groups and "yours" in groups:
        assert groups.index("yours") < groups.index("presets")
    dogfood = next(r for r in rows if r.name == "dogfood")
    assert dogfood.group == "yours"
    assert "main" in dogfood.summary and "3" in dogfood.summary


def test_picker_classifies_builtins_as_presets(tmp_path):
    rows = tui_state.profile_picker_groups(_snapshot(tmp_path))
    builtins = [r for r in rows if r.source_label == "builtin"]
    assert builtins  # the bundled expert profiles
    assert all(r.group == "presets" for r in builtins)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py -q`
Expected: FAIL — `AttributeError: ... 'profile_picker_groups'`.

- [ ] **Step 3: Implement the view-model**

Append to `src/code_review_loop/tui_state.py`:

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


def profile_picker_groups(snapshot: HomeSnapshot) -> tuple[ProfilePickerRow, ...]:
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
            self.selected_index = min(self.selected_index, max(0, len(rows) - 1))

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
    rows = tui_state.profile_picker_groups(app.model.snapshot)
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
            self._profile_picker.set_rows(tui_state.profile_picker_groups(self.model.snapshot))
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
git add src/code_review_loop/tui_state.py src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): grouped profiles picker that loads into the loop"
```

---

## Task 2: Prompts inventory view-model (pure)

A browse-only inventory of the fragment-composed prompt assets, tagged with trust/source — the data behind the library.

**Files:**
- Modify: `src/code_review_loop/tui_state.py`
- Test: `tests/test_tui_profiles_prompts_view.py`

**Interfaces:**
- Consumes: the packaged `code_review_loop.prompts` resources (`fragments/*.txt`, `triage_v1.txt`, `triage_v2.txt`) via `importlib.resources`; `prompts_composer.load_fragment` for trusted-builtin resolution.
- Produces:
  - `@dataclass(frozen=True) class PromptAsset`: `name`, `kind` (`"fragment"`/`"contract"`), `trust` (`"builtin"`), `preview` (first ~80 chars).
  - `prompt_inventory() -> tuple[PromptAsset, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_profiles_prompts_view.py`:

```python
def test_prompt_inventory_lists_builtin_fragments_and_contracts():
    assets = tui_state.prompt_inventory()
    names = {a.name for a in assets}
    assert "security-checklist" in names
    assert any(a.kind == "contract" and a.name.startswith("triage_v") for a in assets)
    sec = next(a for a in assets if a.name == "security-checklist")
    assert sec.kind == "fragment" and sec.trust == "builtin" and sec.preview


def test_prompt_inventory_is_sorted_and_stable():
    a1 = tui_state.prompt_inventory()
    a2 = tui_state.prompt_inventory()
    assert a1 == a2
    fragment_names = [a.name for a in a1 if a.kind == "fragment"]
    assert fragment_names == sorted(fragment_names)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py -k prompt_inventory -q`
Expected: FAIL — `AttributeError: ... 'prompt_inventory'`.

- [ ] **Step 3: Implement**

Append to `src/code_review_loop/tui_state.py` (add `from importlib.resources import files` near the top imports if not present):

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
git add src/code_review_loop/tui_state.py tests/test_tui_profiles_prompts_view.py
git commit -m "feat(tui): prompt inventory view-model (browse-only)"
```

---

## Task 3: Prompts library widget + harness-aware prompt field label

**Files:**
- Modify: `src/code_review_loop/tui_state.py`, `src/code_review_loop/tui_loop_widgets.py`, `src/code_review_loop/tui.py`
- Test: `tests/test_tui_profiles_prompts_view.py`, `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `prompt_inventory` (Task 2); `harnesses` review capability; the loop's `LoopEditModel` for the scalar prompt field values.
- Produces:
  - `prompt_field_label(phase, harness, value) -> str` — harness-aware (codex review → `built-in review (codex)`; otherwise the field value or `<default>`).
  - `prompt_library_class()` lazy widget; `PromptLibrary` browse list (read-only) with `move`, `selected_asset()`, `rebuild`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_profiles_prompts_view.py`:

```python
def test_prompt_field_label_codex_review_is_builtin():
    assert tui_state.prompt_field_label("review", "codex", None) == "built-in review (codex)"


def test_prompt_field_label_external_shows_value_or_default():
    assert tui_state.prompt_field_label("triage", "claude", None) == "<default>"
    assert tui_state.prompt_field_label("triage", "claude", "Focus on docs drift") == (
        "Focus on docs drift"
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

Append to `src/code_review_loop/tui_state.py`:

```python
def prompt_field_label(phase: str, harness: str | None, value: str | None) -> str:
    if phase == "review" and harness == "codex":
        return "built-in review (codex)"
    if value:
        return value
    return "<default>"
```

- [ ] **Step 4: Implement the `PromptLibrary` widget**

Append to `src/code_review_loop/tui_loop_widgets.py` (lazy factory). It is **browse-only** — selecting an asset copies its name for reference; fragment-list insertion into a route is deferred (see Global Constraints):

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
            self.assets = tui_state.prompt_inventory()
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

- [ ] **Step 5: Mount into the Prompts workspace in `tui.py`**

Mirror Task 1's profiles-pane mounting: a `_prompt_library_widget(app)` helper that builds the widget and stores `app._prompt_library`; a `#prompts-pane` `_Vertical` in `compose`; display-toggle in `_render_workbench` (`on_prompts = self._workspace == "prompts"`); navigation delegation in `_move_selection`; CSS `#prompts-pane { width: 1fr; height: 1fr; padding: 0 1; overflow-y: auto; }`. Initialise `self._prompt_library = None` in `__init__`.

- [ ] **Step 6: Run tests + TUI suite**

Run: `python -m pytest tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/code_review_loop/tui_state.py src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_profiles_prompts_view.py tests/test_tui_pilot_smoke.py
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
            await pilot.press("2")  # Loop
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
- Test: `tests/test_tui_pilot_smoke.py`, `tests/test_tui_loop_model.py`

**Interfaces:**
- Consumes: `LoopEditModel.set_field`/`save`; the loop's triage routes (`profile.triage.routes`); `HARNESS_CHOICES`/`EFFORT_CHOICES` (Plan 2); `profiles.set_profile_field` (for the equivalence test).
- Produces: `route_edit_modal_class()` (a `ModalScreen` with per-cell inputs); `action_edit_route` + `action_add_route` on the app, bound on the Loop workspace when triage is focused.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_loop_model.py` (locks route-edit CLI-equivalence, the new risk this task introduces):

```python
def test_route_cell_edit_round_trips_to_config_set(tmp_path):
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
```

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
            await pilot.press("2")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_loop_model.py -k route_cell tests/test_tui_pilot_smoke.py -k route_edit -q`
Expected: FAIL — `_apply_route_edit` not defined (pilot); the model round-trip test should PASS already if Plan 2's `save_profile_raw` path is correct (it is the equivalence lock — keep it).

- [ ] **Step 3: Implement the route-edit apply path + modal**

In `src/code_review_loop/tui.py`, add the apply helpers (the modal is a UI affordance over these; the helpers are what the tests and the modal both call):

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
            on_submit=lambda name: self._apply_route_edit(name, "harness", "codex"),
        )
```

Add the `route_edit_modal_class()` factory to `src/code_review_loop/tui_loop_widgets.py` — a `ModalScreen` (mirror `tui.text_prompt_screen_class`) presenting the route's cells as cyclable/enterable fields and calling back with `(route, cell, value)` tuples on submit. Bind `a` → `action_add_route` on the Loop workspace; the route-edit modal opens from the triage-focused card on `Enter` (extend Plan 2's `action_select`/expand handling to detect a triage-route selection).

**Deferred (stated, not built):** route **deletion** (`x remove` in the design mockup) — the working-copy `save_profile_raw` is merge-only and cannot remove a route key; this needs a delete-capable primitive (future plan). The route-edit modal must not offer a remove action that silently no-ops.

- [ ] **Step 4: Run tests + full suite**

Run: `python -m pytest tests/test_tui_loop_model.py tests/test_tui_pilot_smoke.py -q && python -m pytest -q`
Expected: PASS repo-wide.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py tests/test_tui_loop_model.py
git commit -m "feat(tui): edit triage route cells + add route via working copy"
```

---

## Task 6: Documentation + changelog + final verification

**Files:**
- Modify: `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`

- [ ] **Step 1: Document profiles, prompts, and route editing**

In `docs/70-devex/devex-001-using-code-review-loop.md`, add subsections: the **Profiles** workspace (grouped picker; `Enter` loads a saved loop into the editor; lifecycle actions still shell through `revrem config`; builtins are clone-to-edit); the **Prompts** library (browse fragments + triage contracts; **fragment-list editing is not yet available** — pick scalar prompt fields in-loop with `e`); **route editing** from the triage phase (`Enter` to edit a route's cells, `a` to add a route; **route deletion is not yet available**).

- [ ] **Step 2: CHANGELOG entry**

Under Unreleased → Added:

```
- TUI: profiles workspace is now a grouped save/load picker that loads a profile
  into the live loop editor; a browse-only prompts library lists fragment-composed
  assets; triage route cells and scalar prompt fields (triage.prompt,
  commit.message_prompt) are editable in-loop through the working copy.
```

Under Unreleased → Notes (or Known limitations), state the two deferred items:

```
- TUI route deletion and prompt-fragment list editing are deferred (the current
  profile-save primitive is merge-only / scalar-only).
```

- [ ] **Step 3: Final full-suite + lint/format gate**

Run: `python -m pytest -q`
Expected: PASS.
Run the repo's configured `ruff check` / `ruff format --check` per `pyproject.toml`.
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add docs/70-devex/devex-001-using-code-review-loop.md CHANGELOG.md
git commit -m "docs(tui): document profiles picker, prompts library, route editing"
```

---

## Self-review (run by the plan author before execution)

**Spec coverage (REVREM-DESIGN-001 §5.3, §5.4, §6, and §5.1 route editing):**
- Profiles demoted to a grouped save/load picker (yours vs presets), load-into-loop → Task 1. ✓
- Lifecycle actions still shell through `revrem config` → reused `tui_state.*_plan_for_name` (unchanged). ✓
- Prompts library (browse surface) + in-loop picking → Tasks 2–4; fragment-list curation **reserved/deferred** with stated reason (matches §5.4 "library surface + in-loop picking; advanced curation reserved"). ✓
- Harness-aware prompt field (codex review built-in) → `prompt_field_label` (Task 3). ✓
- Triage route-row editing (the Plan 2 read-only table) → `RouteEditModal` + `_apply_route_edit` (Task 5); deletion deferred with stated reason. ✓
- All edits flow through the working copy + the verified-equivalent save path → `LoopEditModel.set_field`/`save`; round-trip equivalence test (Task 5). ✓

**Honesty about limits (a reviewer rewards this):** two structurally-identical merge-only/scalar-only gaps (route deletion; fragment-list editing) are both deferred with the *same* root-cause explanation and surfaced in the docs — not one handled and one quietly promised.

**Placeholder scan:** none — every code/test step shows complete content, except Task 5's `route_edit_modal_class` UI body, which is specified by behaviour + the concrete `_apply_route_edit`/`action_add_route` helpers the tests exercise (the modal is a thin affordance over tested helpers; its layout mirrors the existing `TextPrompt` modal). If the executor wants a failing test for the modal's compose, add one asserting the modal yields one input per route cell.

**Type consistency:** `profile_picker_groups`/`ProfilePickerRow`, `prompt_inventory`/`PromptAsset`, `prompt_field_label`, and the widget factories `profile_picker_class`/`prompt_library_class`/`route_edit_modal_class` match between definition and `tui.py` use. Raw keys (`triage.prompt`, `commit.message_prompt`, `triage.routes.<name>.<cell>`) match the verified schema. `LoopEditModel.set_field`/`field_value`/`save` calls match Plan 2's signatures.

**Dependency on Plans 2–3:** reuses `LoopEditModel`, `HARNESS_CHOICES`/`EFFORT_CHOICES`, the `#loop-pane`/`app._loop_diagram` wiring, the display-toggle layout, and the `tui_loop_widgets` lazy-factory + `TextPrompt` modal patterns. Flagged in the sequencing note; re-confirm before Task 1.
