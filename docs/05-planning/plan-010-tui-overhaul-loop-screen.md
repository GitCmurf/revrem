---
document_id: REVREM-PLAN-010
type: PLAN
title: TUI Overhaul Plan 2 — Loop Screen (editable diagram + working copy)
status: Draft
version: '0.7'
last_updated: '2026-06-28'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Plan 2 of the loop-first TUI overhaul (REVREM-DESIGN-001): build the
  authoring Loop screen as real interactive Textual widgets (LoopDiagram / PhaseCard
  / TriageRoutesTable) fed by pure tui_loop_state view-models, on a working-copy + explicit-save
  state model that persists through the Plan 1 save_profile_raw primitive.'
keywords:
- tui
- loop-screen
- textual-widgets
- working-copy
- save-profile-raw
- design-001
related_ids:
- REVREM-DESIGN-001
- REVREM-PLAN-009
- REVREM-PRD-001
---

# TUI Overhaul Plan 2 — Loop Screen (editable diagram + working copy)

> **For agentic workers:** Implement this plan task-by-task using the repo's normal TDD loop: write the named failing tests first, make the smallest scoped implementation, run the listed verification, then commit only the task's files. Steps use checkbox (`- [ ]`) syntax for tracking. Do not rely on external "superpowers" skills; they are not part of this repository contract.

**Goal:** Make the Loop the editable centre of the TUI — a vertical, config-truthful diagram of real interactive Textual widgets that lets the operator edit harness / model / effort / timeout / enable per phase (and triage's routing-level fields) into an in-memory working copy, then persist the whole copy to the owning profile file in one explicit Save.

**Architecture:** Three layers, bottom-up. (1) A pure, Textual-free **working-copy model** (`LoopEditModel`) holds the resolved baseline `Profile` plus a dict of meaningful pending dotted-key edits; it renders effective field values (edit overlays baseline), drops no-op/reverted edits, produces an authored raw delta, and persists through Plan 1's `profiles.save_profile_raw`. (2) Pure **view-model functions** in a new `tui_loop_state.py` turn the model into per-phase card lines, a loop header, rail metadata, and the triage routes table — config-truthful (inner rail only when `runtime.inner_check_retries > 0`, disabled phases marked and dropped from the rails, final review shown only when on). These authoring helpers read effective values from the working copy, while also accepting plain resolved profiles for Plan 3's live view. `tui_state.py` remains the home/shell/history module; it may re-export or import loop helpers only where needed for `render_shell_text`. (3) Real **Textual widgets** in a new `tui_loop_widgets.py` (`PhaseCard`, `TriageRoutesTable`, `LoopDiagram`) consume those view-models, own focus/selection/inline-edit keyboard handling, and mount into the existing app's Loop workspace. The same view-models keep `render_shell_text` working as the headless fallback.

**Tech Stack:** Python 3.12, Textual 8.2.5 (optional `[tui]` extra, lazy-imported), `pytest` + Textual pilot/`run_test`, the Plan 1 `profiles` edit primitives (`deep_set_raw`, `save_profile_raw`, `set_profile_field`).

## Plan sequence (this is Plan 2 of 4)

1. **Plan 1 (REVREM-PLAN-009):** edit primitives — library + `config set`. **COMPLETE.**
2. **Plan 2 (this doc):** authoring Loop screen — working-copy model + `LoopDiagram` / `PhaseCard` / `TriageRoutesTable` widgets + Save→profile.
3. **Plan 3:** run / monitor live mode — the same diagram, live (`LoopRunView`, `EventLog`).
4. **Plan 4:** profiles picker + prompts library + in-loop prompt picking + route-row modal editing.

## Global Constraints

Every task's requirements implicitly include this section. These constraints reconcile REVREM-DESIGN-001 with the Plan 1 profile-edit primitives already shipped.

- **Working copy + explicit save (option A).** Inline edits mutate an in-memory working copy only — never one CLI/disk write per keystroke. A `*` marks unsaved changes. **Save → profile** persists the whole working copy in one call to `profiles.save_profile_raw(name, authored_delta, cwd=..., home=...)`. **Run** launches `revrem --profile NAME`; if the working copy is dirty, Run offers *save-and-run* (persist, then launch).
- **The diagram is config-truthful.** What is shown equals what the profile will do: the inner remediation⇄checks rail is drawn **only** when `runtime.inner_check_retries > 0`; disabled phases are marked disabled and drop out of the loop rails; the `final review` row is shown **only** when raw `pipeline.final_review` resolves true.
- **Validation timing (explicit Plan-2 scope decision).** Enumerated fields (harness, reasoning effort, the boolean enables) are edited by cycling through known-valid choices, so they cannot reach an invalid value in the working copy. Free-text fields (model, timeout) are edited through text entry and validated at **Save** time (where `save_profile_raw` → `parse_profile` raises `ValueError`), and the error surfaces on the Save action; the working copy is not blocked per-keystroke. Per-field inline validation as-you-type is deferred to Plan 4. This is a deliberate narrowing of REVREM-DESIGN-001 §7 for this iteration, not an oversight. Route sandbox remains read-only in Plan 2 because route-row editing is Plan 4.
- **CLI-equivalence is preserved.** The TUI still launches runs as `revrem --profile NAME` and persists config through the same library write path the CLI uses. `assert_equivalent_run_artifacts` parity and the existing `test_tui_cli_equivalence.py` must continue to pass.
- **Textual stays an optional dependency.** All Textual widget/screen classes are defined lazily through factory functions (mirroring the existing `text_prompt_screen_class()` in `tui.py`); importing `code_review_loop.tui` / `tui_loop_widgets` must not require Textual. When Textual is absent, `render_shell_text` remains the headless view.
- **Dirty means semantically different.** `LoopEditModel.edits` stores only meaningful deltas from the resolved baseline. Setting a field to its existing value, or editing a value and then reverting it, removes that edit and clears the `*` marker when no other edits remain.
- **Raw dotted-key contract.** `LoopEditModel` stores and saves **raw profile TOML keys**, not display-layer field names. Loop pipeline keys live under the raw `[pipeline]` table: `pipeline.base`, `pipeline.max_iterations`, and `pipeline.final_review`. Nested sections keep their section prefix (`review.model`, `runtime.inner_check_retries`, `triage.routing.default_route`, etc.). Any view-model label may say "max iterations", but the edit key passed to `profiles.deep_set_raw` / `save_profile_raw` must be the raw key.
- **Scope of edits in Plan 2.** Editable from the loop: per-phase `enabled` (where the phase has one), `harness`, `model` (commit uses `message_model`), `reasoning_effort`, `timeout_seconds`; loop meta raw keys `pipeline.max_iterations`, `pipeline.final_review`, `runtime.inner_check_retries`; triage routing-level `triage.routing.default_route`, `triage.routing.strict_on_unavailable_route`, `triage.routing.allow_model_escalation`. **Out of scope (Plan 4):** editing individual triage route-table cells (rendered read-only here), prompt picking/editing, and the profiles/prompts/run screens (left as their current markup until their plans).
- **Branch & commits.** Work on `feat/tui-live-runs` (never `main`). Stage files explicitly per task — never `git add -A`. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm
  ```

## Pre-flight note for the executor

REVREM-DESIGN-001's write-path language is **stale**: §2/§3 still imply all config writes shell through `revrem config`, §4.2 says Save will reuse `config import` while explicitly rejecting `config set`, and §7 says validation surfaces a `revrem config` error even though Plan 2 saves through `save_profile_raw` and receives `ValueError` directly. Plan 1 shipped both `config set` and the `save_profile_raw` library writer, and Plan 2 calls `save_profile_raw` in-process. **Task 1, Step 0 updates those design sections** so the design matches the shipped code before any widget work — otherwise the final whole-branch reviewer will (correctly) flag a code-vs-spec mismatch.

---

## File structure

- **Create** `src/code_review_loop/tui_loop_model.py` — `LoopEditModel` working copy (pure; imports only `profiles`).
- **Create** `src/code_review_loop/tui_loop_state.py` — pure loop view-model functions (header, per-phase card lines, rail metadata, triage routes lines). Keep `tui_state.py` focused on the existing shell/home/history view-models; only add compatibility imports there if `render_shell_text` needs them.
- **Create** `src/code_review_loop/tui_loop_widgets.py` — lazy Textual widget factories: `PhaseCard`, `TriageRoutesTable`, `LoopDiagram`.
- **Modify** `src/code_review_loop/tui.py` — mount the `LoopDiagram` into the Loop workspace; reorder nav to Loop-first; wire Save / save-and-run and the dirty `*` indicator.
- **Create** `tests/test_tui_loop_model.py`, `tests/test_tui_loop_view.py` — pure-layer unit tests.
- **Modify** `tests/test_tui_pilot_smoke.py` — widget pilot tests + updated nav assertions.
- **Create** `tests/test_tui_loop_snapshots.py` — SVG/rendered-output snapshots for representative `LoopDiagram` states.
- **Modify** `docs/30-design/design-001-loop-first-tui-overhaul.md`, `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`.

---

## Task 1: Working-copy model (`LoopEditModel`)

The pure foundation: holds the resolved baseline profile plus pending edits, overlays edits onto displayed values, builds the authored delta, and saves through Plan 1's primitive. No Textual.

**Files:**
- Create: `src/code_review_loop/tui_loop_model.py`
- Modify: `docs/30-design/design-001-loop-first-tui-overhaul.md` (§4.2 staleness fix)
- Test: `tests/test_tui_loop_model.py`

**Interfaces:**
- Consumes (from Plan 1, `code_review_loop.profiles`): `deep_set_raw(raw, dotted_key, value) -> dict`; `save_profile_raw(name, raw_profile, *, cwd, home=None) -> Path`; `set_profile_field(name, dotted_key, value, *, cwd, home=None) -> Path`; `resolve_profile(name, *, cwd, home=None, require_implemented=...) -> Profile`.
- Produces (for Tasks 2 & 4):
  - `class LoopEditModel` with: `name: str`, `profile: profiles.Profile`, `cwd: Path`, `home: Path | None`, `edits: dict[str, str]`.
  - `LoopEditModel.load(name, *, cwd, home=None) -> LoopEditModel` (classmethod).
  - `is_dirty -> bool` (property).
  - `field_value(dotted_key: str, fallback: object) -> object` — coerced pending edit if present, else `fallback`. `dotted_key` is the raw profile TOML key (`pipeline.max_iterations`, not a display-only label).
  - `set_field(dotted_key: str, value: str) -> None` — stores only meaningful deltas; no-op or reverted values remove the edit.
  - `authored_delta() -> dict[str, object]`.
  - `save() -> Path` — persists `authored_delta()` via `save_profile_raw`, clears `edits`, reloads `profile`.

- [ ] **Step 0: Update stale design sections**

In `docs/30-design/design-001-loop-first-tui-overhaul.md`, fix every stale write-path statement before implementing widgets:

1. In §2 Non-goals, replace:

```
- Replacing the CLI write path. All edits continue to shell through `revrem config`.
```

with:

```
- Replacing the profile persistence semantics. TUI writes continue to use the same
  profile edit library used by the CLI (`profiles.save_profile_raw` / `config set`);
  the TUI does not invent a separate config format or hidden run-only overrides.
```

2. In §3 principle 4, replace "writes config exactly as the CLI does" with "writes config through the same profile edit library as the CLI".

3. In §4.2 item 2, replace the parenthetical rejection so it reflects shipped reality. Change the sentence that currently reads:

```
2. **Save → profile** persists the whole working copy in one write. Implementation reuses
   the non-interactive `config import` path (serialize the working copy to TOML, import
   under the target name with `--force`) rather than introducing a brand-new granular
   setter. (Alternative considered: add `revrem config set <profile> <key> <value>` so
   each edit persists immediately — rejected for this iteration: more CLI surface, and
   auto-persist conflicts with the "save game" model.)
```

to:

```
2. **Save → profile** persists the whole working copy in one write, via the library
   writer `profiles.save_profile_raw(name, authored_delta, ...)` shipped in Plan 1
   (REVREM-PLAN-009). The TUI accumulates edits as a raw authored delta and calls this
   in-process — no per-keystroke persistence. Plan 1 *also* shipped the scriptable
   `revrem config set <profile> <key> <value>` (one-shot, immediate-persist) for the
   "everything in the CLI" principle; the TUI deliberately does not use the
   immediate-persist path, because auto-persist conflicts with the "save game" model.
```

4. In §7 Error handling, replace any claim that failed TUI saves surface a `revrem config` shell error with library validation wording: `save_profile_raw` calls `parse_profile`, raises `ValueError`, and the TUI shows that error inline while leaving the working copy dirty for correction.

- [ ] **Step 0b: Lock the pipeline raw-key contract before depending on it**

Plan 2 edits `max_iterations` and `final_review` through their raw pipeline keys. Before writing `LoopEditModel`, add focused tests to the existing profile-edit coverage proving these calls work:

```python
profiles.deep_set_raw({}, "pipeline.max_iterations", "9") == {
    "pipeline": {"max_iterations": 9}
}
profiles.deep_set_raw({}, "pipeline.final_review", "false") == {
    "pipeline": {"final_review": False}
}
```

Also verify `profiles.set_profile_field("dogfood", "pipeline.max_iterations", "9", cwd=repo)` and `profiles.set_profile_field("dogfood", "pipeline.final_review", "false", cwd=repo)` persist valid TOML that reloads through `resolve_profile`. Root-level `max_iterations` / `final_review` are intentionally invalid raw profile keys; do not add coercion or compatibility behavior for them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_loop_model.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import profiles
from code_review_loop.tui_loop_model import LoopEditModel


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project_profile(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "\n".join(
            (
                "[profiles.dogfood]",
                "[profiles.dogfood.pipeline]",
                'base = "main"',
                "max_iterations = 4",
                "[profiles.dogfood.review]",
                'harness = "codex"',
                'model = "gpt-5.5"',
            )
        )
        + "\n",
    )
    return repo


def test_field_value_returns_fallback_when_unedited(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    assert model.field_value("review.model", model.profile.review.model) == "gpt-5.5"
    assert model.is_dirty is False


def test_set_field_overlays_and_coerces(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.set_field("pipeline.max_iterations", "9")
    model.set_field("pipeline.final_review", "false")
    assert model.field_value("review.model", "gpt-5.5") == "gpt-5.6"
    # coercion: max_iterations is an int field
    assert model.field_value("pipeline.max_iterations", 4) == 9
    assert model.field_value("pipeline.final_review", True) is False
    assert model.is_dirty is True


def test_authored_delta_nests_dotted_keys(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.set_field("runtime.inner_check_retries", "2")
    model.set_field("pipeline.max_iterations", "9")
    delta = model.authored_delta()
    assert delta == {
        "review": {"model": "gpt-5.6"},
        "runtime": {"inner_check_retries": 2},
        "pipeline": {"max_iterations": 9},
    }


def test_save_persists_clears_dirty_and_reloads(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    path = model.save()
    assert path == repo / ".revrem.toml"
    assert model.is_dirty is False
    assert model.profile.review.model == "gpt-5.6"
    # persisted on disk
    reloaded = profiles.resolve_profile("dogfood", cwd=repo, require_implemented=False)
    assert reloaded.review.model == "gpt-5.6"


def test_save_round_trips_to_config_set_path(tmp_path):
    # The new CLI-equivalence risk Plan 2 introduces: a working-copy edit persisted via
    # the model must yield the SAME persisted profile as the equivalent config-set call.
    repo_model = _project_profile(tmp_path / "via_model")
    repo_set = _project_profile(tmp_path / "via_set")

    model = LoopEditModel.load("dogfood", cwd=repo_model)
    model.set_field("review.model", "gpt-5.6")
    model.save()

    profiles.set_profile_field("dogfood", "review.model", "gpt-5.6", cwd=repo_set)

    via_model = (repo_model / ".revrem.toml").read_text(encoding="utf-8")
    via_set = (repo_set / ".revrem.toml").read_text(encoding="utf-8")
    assert via_model == via_set


def test_save_surfaces_validation_error(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("pipeline.max_iterations", "-1")
    with pytest.raises(ValueError):
        model.save()
    # edits remain so the operator can correct them
    assert model.is_dirty is True


def test_set_field_does_not_dirty_for_baseline_value(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.5")
    assert model.edits == {}
    assert model.is_dirty is False


def test_set_field_revert_removes_pending_edit(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    assert model.is_dirty is True
    model.set_field("review.model", "gpt-5.5")
    assert model.edits == {}
    assert model.is_dirty is False


def test_set_field_coercion_equivalent_values_are_not_dirty(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("pipeline.max_iterations", "4")
    model.set_field("pipeline.final_review", "true")
    assert model.edits == {}
    assert model.is_dirty is False


def test_baseline_projection_covers_every_editable_dotted_key(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    keys = [
        "pipeline.max_iterations",
        "pipeline.final_review",
        "runtime.inner_check_retries",
        "review.harness",
        "review.model",
        "review.reasoning_effort",
        "review.timeout_seconds",
        "triage.enabled",
        "triage.harness",
        "triage.model",
        "triage.reasoning_effort",
        "triage.timeout_seconds",
        "triage.routing.default_route",
        "triage.routing.strict_on_unavailable_route",
        "triage.routing.allow_model_escalation",
        "remediation.harness",
        "remediation.model",
        "remediation.reasoning_effort",
        "remediation.timeout_seconds",
        "commit.enabled",
        "commit.harness",
        "commit.message_model",
        "commit.reasoning_effort",
        "commit.timeout_seconds",
    ]
    raw = _profile_to_raw(model.profile)
    for key in keys:
        assert _read_dotted(raw, key) == model.field_value(
            key, _read_dotted(raw, key)
        )


def test_builtin_profile_save_is_readonly_until_cloned(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_loop_model.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'code_review_loop.tui_loop_model'`.

- [ ] **Step 3: Write the implementation**

Create `src/code_review_loop/tui_loop_model.py`:

```python
"""In-memory working-copy model for the TUI Loop screen.

Holds a resolved baseline profile plus a dict of pending dotted-key edits.
Display values overlay edits onto the baseline; Save persists the authored
delta through the Plan 1 ``profiles.save_profile_raw`` primitive. Pure: this
module imports only ``profiles`` and the standard library — no Textual.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import reduce
from pathlib import Path

from code_review_loop import profiles


def _read_dotted(data: object, dotted_key: str) -> object:
    """Read a dotted key out of a nested dict produced by ``deep_set_raw``."""
    cursor: object = data
    for part in dotted_key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(dotted_key)
        cursor = cursor[part]
    return cursor


def _profile_to_raw(profile: profiles.Profile) -> dict[str, object]:
    """Render a resolved profile to raw-ish TOML keys for baseline comparisons."""
    raw = asdict(profile)
    raw.pop("name", None)
    raw.pop("source", None)
    return raw


@dataclass
class LoopEditModel:
    """A profile loaded for editing, with pending in-memory edits."""

    name: str
    profile: profiles.Profile
    cwd: Path
    home: Path | None = None
    edits: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, name: str, *, cwd: Path, home: Path | None = None) -> "LoopEditModel":
        profile = profiles.resolve_profile(
            name, cwd=cwd, home=home, require_implemented=False
        )
        return cls(name=name, profile=profile, cwd=cwd, home=home)

    @property
    def is_dirty(self) -> bool:
        return bool(self.edits)

    def field_value(self, dotted_key: str, fallback: object) -> object:
        """Effective value: the coerced pending edit if present, else ``fallback``."""
        if dotted_key not in self.edits:
            return fallback
        coerced = profiles.deep_set_raw({}, dotted_key, self.edits[dotted_key])
        return _read_dotted(coerced, dotted_key)

    def set_field(self, dotted_key: str, value: str) -> None:
        coerced = profiles.deep_set_raw({}, dotted_key, value)
        proposed = _read_dotted(coerced, dotted_key)
        try:
            baseline = _read_dotted(_profile_to_raw(self.profile), dotted_key)
        except KeyError:
            self.edits[dotted_key] = value
            return
        if proposed == baseline:
            self.edits.pop(dotted_key, None)
        else:
            self.edits[dotted_key] = value

    def authored_delta(self) -> dict[str, object]:
        return reduce(
            lambda acc, item: profiles.deep_set_raw(acc, item[0], item[1]),
            self.edits.items(),
            {},
        )

    def save(self) -> Path:
        # save_profile_raw/profile_owner_path raises the clone-to-edit RuntimeError
        # for builtin profiles; keep that message intact for the TUI.
        path = profiles.save_profile_raw(
            self.name, self.authored_delta(), cwd=self.cwd, home=self.home
        )
        self.edits.clear()
        self.profile = profiles.resolve_profile(
            self.name, cwd=self.cwd, home=self.home, require_implemented=False
        )
        return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_loop_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_loop_model.py tests/test_tui_loop_model.py docs/30-design/design-001-loop-first-tui-overhaul.md
git commit -m "feat(tui): add LoopEditModel working-copy + fix stale design 4.2"
```

---

## Task 2: Loop diagram view-models (pure functions in `tui_loop_state`)

Per-phase card lines, the loop header, and rail metadata — config-truthful, Textual-free, so they can be unit-tested directly and reused by `render_shell_text`.

**Files:**
- Create: `src/code_review_loop/tui_loop_state.py`
- Modify: `src/code_review_loop/tui_state.py` only if needed to keep `render_shell_text` using the new loop helpers without duplicating logic.
- Test: `tests/test_tui_loop_view.py`

**Interfaces:**
- Consumes: `LoopEditModel` (Task 1); `profiles.Profile`; existing `harnesses.phase_effort_text(harness, effort)`.
- Produces (for Tasks 3 & 4):
  - `LOOP_PHASES: tuple[str, ...] = ("review", "triage", "remediation", "checks", "commit")`
  - `LOOP_META_DOTTED: dict[str, str] = {"max_iterations": "pipeline.max_iterations", "final_review": "pipeline.final_review", "inner_check_retries": "runtime.inner_check_retries"}` — raw edit keys for loop-level fields.
  - `PHASE_DOTTED: dict[str, dict[str, str]]` — per-phase map of edit-target dotted keys (see code).
  - `loop_header_text(source) -> str` — `source` may be `LoopEditModel` or `profiles.Profile`; working-copy mode overlays pending edits.
  - `@dataclass(frozen=True) class LoopRailMeta` with `max_iterations: int`, `inner_check_retries: int`, `inner_rail: bool`, `final_review: bool`, `outer_return_label: str`, `inner_return_label: str | None`, `final_review_label: str | None`.
  - `loop_rail_meta(source) -> LoopRailMeta` — same source contract as `loop_header_text`.
  - `phase_card_lines(model, phase, *, focused, expanded) -> tuple[str, ...]`
  - `phase_gutter(phase, rail_meta) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_loop_view.py`:

```python
from __future__ import annotations

from pathlib import Path

from code_review_loop import profiles, tui_loop_state
from code_review_loop.tui_loop_model import LoopEditModel


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / ".revrem.toml", body)
    return repo


def _model(repo: Path, name: str) -> LoopEditModel:
    return LoopEditModel.load(name, cwd=repo)


def test_rail_meta_omits_inner_rail_when_retries_zero(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=5\n[profiles.p.runtime]\ninner_check_retries=0\n",
    )
    meta = tui_loop_state.loop_rail_meta(_model(repo, "p").profile)
    assert meta.inner_rail is False
    assert meta.inner_return_label is None
    assert "iteration < 5" in meta.outer_return_label


def test_rail_meta_draws_inner_rail_when_retries_positive(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=5\n[profiles.p.runtime]\ninner_check_retries=2\n",
    )
    meta = tui_loop_state.loop_rail_meta(_model(repo, "p").profile)
    assert meta.inner_rail is True
    assert meta.inner_return_label is not None
    assert "up to 2 inner retries" in meta.inner_return_label


def test_rail_meta_final_review_only_when_on(tmp_path):
    on = _repo(tmp_path / "on", "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nfinal_review=true\n")
    off = _repo(tmp_path / "off", "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nfinal_review=false\n")
    assert tui_loop_state.loop_rail_meta(_model(on, "p").profile).final_review is True
    assert tui_loop_state.loop_rail_meta(_model(off, "p").profile).final_review is False
    assert tui_loop_state.loop_rail_meta(_model(off, "p").profile).final_review_label is None


def test_phase_gutter_shows_inner_rail_and_final_review_together(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nfinal_review=true\n"
        "[profiles.p.runtime]\ninner_check_retries=2\n",
    )
    meta = tui_loop_state.loop_rail_meta(_model(repo, "p").profile)
    remediation = tui_loop_state.phase_gutter("remediation", meta)
    checks = tui_loop_state.phase_gutter("checks", meta)
    assert meta.inner_rail is True
    assert meta.final_review is True
    assert "inner" in remediation.lower()
    assert "inner" in checks.lower()
    assert meta.final_review_label is not None


def test_phase_card_summary_shows_harness_model_and_disabled_marker(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    review = tui_loop_state.phase_card_lines(model, "review", focused=False, expanded=False)
    text = "\n".join(review)
    assert "review" in text and "codex" in text and "gpt-5.5" in text
    assert text.lstrip().startswith(f"▸ {tui_loop_state.PHASE_ENABLED_GLYPH}")
    # triage defaults off -> disabled glyph
    triage = tui_loop_state.phase_card_lines(model, "triage", focused=False, expanded=False)
    assert "\n".join(triage).lstrip().startswith(f"▸ {tui_loop_state.PHASE_DISABLED_GLYPH}")


def test_phase_card_focused_collapsed_remains_single_summary_line(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    lines = tui_loop_state.phase_card_lines(
        _model(repo, "p"), "review", focused=True, expanded=False
    )
    assert len(lines) == 1
    assert lines[0].startswith(">")
    assert "harness" not in lines[0].lower()


def test_phase_card_expanded_shows_edit_fields_with_overlay(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    model.set_field("review.model", "gpt-5.6")
    expanded = tui_loop_state.phase_card_lines(model, "review", focused=True, expanded=True)
    text = "\n".join(expanded)
    assert text.lstrip().startswith("▾")
    assert "harness" in text and "model" in text and "effort" in text and "timeout" in text
    # overlay reflected, not the baseline
    assert "gpt-5.6" in text and "gpt-5.5" not in text


def test_phase_card_timeout_overlay_formats_int_and_float_values(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    model.set_field("review.timeout_seconds", "0.5")
    assert "0.5s" in "\n".join(
        tui_loop_state.phase_card_lines(model, "review", focused=False, expanded=False)
    )
    model.set_field("review.timeout_seconds", "1")
    assert "1s" in "\n".join(
        tui_loop_state.phase_card_lines(model, "review", focused=False, expanded=False)
    )


def test_checks_phase_is_display_only(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nchecks=['pytest -q']\n",
    )
    expanded = "\n".join(
        tui_loop_state.phase_card_lines(_model(repo, "p"), "checks", focused=True, expanded=True)
    )
    assert "1 commands" in expanded
    assert "harness" not in expanded and "model" not in expanded
    assert tui_loop_state.PHASE_DOTTED["checks"] == {}


def test_loop_header_reports_meta(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=7\n[profiles.p.runtime]\ninner_check_retries=3\n",
    )
    header = tui_loop_state.loop_header_text(_model(repo, "p").profile)
    assert "main" in header and "7" in header and "3" in header


def test_loop_header_and_rails_reflect_unsaved_meta_edits(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=7\nfinal_review=true\n"
        "[profiles.p.runtime]\ninner_check_retries=0\n",
    )
    model = _model(repo, "p")
    model.set_field("pipeline.max_iterations", "11")
    model.set_field("pipeline.final_review", "false")
    model.set_field("runtime.inner_check_retries", "2")
    header = tui_loop_state.loop_header_text(model)
    meta = tui_loop_state.loop_rail_meta(model)
    assert "11" in header and "2" in header
    assert meta.max_iterations == 11
    assert meta.inner_rail is True
    assert meta.final_review is False
    assert meta.final_review_label is None


def test_loop_meta_dotted_uses_raw_profile_keys():
    assert tui_loop_state.LOOP_META_DOTTED["max_iterations"] == "pipeline.max_iterations"
    assert tui_loop_state.LOOP_META_DOTTED["final_review"] == "pipeline.final_review"
    assert tui_loop_state.LOOP_META_DOTTED["inner_check_retries"] == "runtime.inner_check_retries"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_loop_view.py -q`
Expected: FAIL with `ModuleNotFoundError` or `AttributeError` for `code_review_loop.tui_loop_state.loop_rail_meta`.

- [ ] **Step 3: Write the implementation**

Create `src/code_review_loop/tui_loop_state.py`. Import `dataclass`, `Any`, `harnesses`, `profiles`, and reuse `tui_state.pipeline_phases` / `PhaseView` rather than duplicating the phase projection.

```python
LOOP_PHASES: tuple[str, ...] = ("review", "triage", "remediation", "checks", "commit")
PHASE_ENABLED_GLYPH = "●"  # ●
PHASE_DISABLED_GLYPH = "○"  # ○
LOOP_META_DOTTED: dict[str, str] = {
    "max_iterations": "pipeline.max_iterations",
    "final_review": "pipeline.final_review",
    "inner_check_retries": "runtime.inner_check_retries",
}

# Edit-target dotted keys per phase. ``checks`` has no inline single-field edits
# in Plan 2 (its commands are edited elsewhere); ``commit`` uses ``message_model``.
PHASE_DOTTED: dict[str, dict[str, str]] = {
    "review": {
        "enabled": "",  # review is always on; no enable toggle
        "harness": "review.harness",
        "model": "review.model",
        "effort": "review.reasoning_effort",
        "timeout": "review.timeout_seconds",
    },
    "triage": {
        "enabled": "triage.enabled",
        "harness": "triage.harness",
        "model": "triage.model",
        "effort": "triage.reasoning_effort",
        "timeout": "triage.timeout_seconds",
    },
    "remediation": {
        "enabled": "",  # remediation is always on
        "harness": "remediation.harness",
        "model": "remediation.model",
        "effort": "remediation.reasoning_effort",
        "timeout": "remediation.timeout_seconds",
    },
    "checks": {},
    "commit": {
        "enabled": "commit.enabled",
        "harness": "commit.harness",
        "model": "commit.message_model",
        "effort": "commit.reasoning_effort",
        "timeout": "commit.timeout_seconds",
    },
}


@dataclass(frozen=True)
class LoopRailMeta:
    max_iterations: int
    inner_check_retries: int
    inner_rail: bool
    final_review: bool
    outer_return_label: str
    inner_return_label: str | None
    final_review_label: str | None


def _source_profile(source: "Any") -> profiles.Profile:
    return source.profile if hasattr(source, "profile") else source


def _effective_value(source: "Any", dotted_key: str, fallback: object) -> object:
    if hasattr(source, "field_value"):
        return source.field_value(dotted_key, fallback)
    return fallback


def loop_header_text(source: "Any") -> str:
    profile = _source_profile(source)
    base = _effective_value(source, "pipeline.base", profile.pipeline.base)
    max_iterations = _effective_value(
        source, "pipeline.max_iterations", profile.pipeline.max_iterations
    )
    retries = _effective_value(
        source, "runtime.inner_check_retries", profile.runtime.inner_check_retries
    )
    return (
        f"base {base} · max {max_iterations} "
        f"· stop when clear · inner-check retries: {retries}"
    )


def loop_rail_meta(source: "Any") -> LoopRailMeta:
    profile = _source_profile(source)
    retries = int(
        _effective_value(
            source, "runtime.inner_check_retries", profile.runtime.inner_check_retries
        )
    )
    inner_rail = retries > 0
    final_review = bool(
        _effective_value(source, "pipeline.final_review", profile.pipeline.final_review)
    )
    max_iterations = int(
        _effective_value(
            source, "pipeline.max_iterations", profile.pipeline.max_iterations
        )
    )
    return LoopRailMeta(
        max_iterations=max_iterations,
        inner_check_retries=retries,
        inner_rail=inner_rail,
        final_review=final_review,
        outer_return_label=(
            f"not clear & iteration < {max_iterations} → review"
        ),
        inner_return_label=(
            f"checks failed → remediation   (up to {retries} inner retries)"
            if inner_rail
            else None
        ),
        final_review_label=(
            "final review  (runs once when the loop ends)" if final_review else None
        ),
    )


def _phase_view_by_name(profile: profiles.Profile) -> dict[str, PhaseView]:
    return {phase.name: phase for phase in pipeline_phases(profile)}


def _effective_phase_field(
    model: "Any", phase_name: str, key: str, fallback: object
) -> object:
    dotted = PHASE_DOTTED.get(phase_name, {}).get(key) or ""
    if not dotted:
        return fallback
    return model.field_value(dotted, fallback)


def phase_card_lines(
    model: "Any", phase: str, *, focused: bool, expanded: bool
) -> tuple[str, ...]:
    view = _phase_view_by_name(model.profile).get(phase)
    if view is None:
        return (f"  {PHASE_DISABLED_GLYPH} {phase}",)
    enabled_dotted = PHASE_DOTTED.get(phase, {}).get("enabled") or ""
    enabled = (
        bool(model.field_value(enabled_dotted, view.enabled))
        if enabled_dotted
        else view.enabled
    )
    glyph = PHASE_ENABLED_GLYPH if enabled else PHASE_DISABLED_GLYPH
    harness = _effective_phase_field(model, phase, "harness", view.harness)
    model_name = _effective_phase_field(model, phase, "model", view.model)
    effort_raw = _effective_phase_field(model, phase, "effort", view.reasoning_effort)
    timeout = _effective_phase_field(model, phase, "timeout", view.timeout_seconds)
    effort = harnesses.phase_effort_text(
        harness if isinstance(harness, str) else None,
        effort_raw if isinstance(effort_raw, str) else None,
    )
    summary_bits: list[str] = []
    if isinstance(harness, str) and harness:
        summary_bits.append(harness)
    if isinstance(model_name, str) and model_name:
        summary_bits.append(model_name)
    if effort:
        summary_bits.append(effort)
    if timeout is not None:
        summary_bits.append(f"{float(timeout):g}s")
    if phase == "checks" and view.command_count is not None:
        summary_bits.append(f"{view.command_count} commands")
    pointer = ">" if focused else " "
    chevron = "▾" if expanded else "▸"
    summary = f"{pointer} {chevron} {glyph} {phase} " + " · ".join(summary_bits)
    lines = [summary.rstrip()]
    if expanded and PHASE_DOTTED.get(phase):
        harness_text = harness if isinstance(harness, str) and harness else "-"
        model_text = model_name if isinstance(model_name, str) and model_name else "-"
        effort_text = effort or "-"
        timeout_text = f"{float(timeout):g}s" if timeout is not None else "default"
        lines.append(
            f"      harness ‹ {harness_text} ›   model ‹ {model_text} ›   "
            f"effort ‹ {effort_text} ›   timeout ‹ {timeout_text} ›"
        )
    return tuple(lines)


def phase_gutter(phase: str, rail_meta: LoopRailMeta) -> str:
    """Left-edge rail segment for a phase, stacked to form the loop rails."""
    if phase == "review":
        return "┌▶ "  # ┌▶  outer loop top
    if phase == "remediation" and rail_meta.inner_rail:
        return "│ ┌▶ "  # │ ┌▶  inner loop top
    if phase == "checks" and rail_meta.inner_rail:
        return "│ │ "  # │ │
    return "│ "  # │
```

Note: the `"Any"` annotations on `model` avoid a hard import of `LoopEditModel`. `tui_loop_state` may import the existing `tui_state.pipeline_phases` helper, but `tui_state` must not import `tui_loop_state` at module import time except for a narrow `render_shell_text` compatibility path; this keeps the new loop helpers from turning `tui_state.py` into a catch-all module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_loop_view.py -q`
Expected: PASS.

- [ ] **Step 5: Run the existing view-model + equivalence suites (no regressions)**

Run: `python -m pytest tests/test_tui_loop_view.py tests/test_tui_state.py tests/test_tui_cli_equivalence.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/code_review_loop/tui_loop_state.py src/code_review_loop/tui_state.py tests/test_tui_loop_view.py
git commit -m "feat(tui): add config-truthful loop diagram view-models"
```

---

## Task 3: Triage routes view-model (pure)

The discriminating case: when triage is focused, render the routing-level line plus a read-only routes table (route-row editing is Plan 4).

**Files:**
- Modify: `src/code_review_loop/tui_loop_state.py`
- Test: `tests/test_tui_loop_view.py` (add cases)

**Interfaces:**
- Consumes: `LoopEditModel` or `profiles.Profile` (`triage.routing`, `triage.routes`); `harnesses.phase_effort_text`.
- Produces: `triage_routes_lines(source) -> tuple[str, ...]`; working-copy mode overlays pending route edits.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_loop_view.py`:

```python
def _routes_repo(tmp_path: Path) -> Path:
    body = "\n".join(
        (
            "[profiles.r]",
            "[profiles.r.pipeline]",
            "base='main'",
            "[profiles.r.triage]",
            "enabled=true",
            "[profiles.r.triage.routing]",
            "enabled=true",
            "default_route='security'",
            "strict_on_unavailable_route=false",
            "allow_model_escalation=true",
            "[profiles.r.triage.routes.security]",
            "harness='codex'",
            "model='gpt-5.5'",
            "reasoning_effort='high'",
            "sandbox='read-only'",
            "fallback='nit'",
            "[profiles.r.triage.routes.nit]",
            "harness='claude'",
            "model='haiku-4.5'",
            "reasoning_effort='low'",
            "sandbox='read-only'",
        )
    )
    return _repo(tmp_path, body + "\n")


def test_triage_routes_lines_show_routing_and_table(tmp_path):
    repo = _routes_repo(tmp_path)
    lines = tui_loop_state.triage_routes_lines(_model(repo, "r").profile)
    text = "\n".join(lines)
    assert "default" in text and "security" in text
    assert "strict" in text and "escalate" in text
    assert "security" in text and "gpt-5.5" in text and "high" in text
    assert "nit" in text and "haiku-4.5" in text


def test_triage_routes_lines_empty_when_routing_off(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n[profiles.p.triage]\nenabled=true\n",
    )
    assert tui_loop_state.triage_routes_lines(_model(repo, "p").profile) == ()


def test_triage_routes_lines_reflect_unsaved_route_edits(tmp_path):
    repo = _routes_repo(tmp_path)
    model = _model(repo, "r")
    model.set_field("triage.routes.security.model", "gpt-9")
    model.set_field("triage.routes.security.sandbox", "workspace-write")
    model.set_field("triage.routes.security.fallback", "nit")
    text = "\n".join(tui_loop_state.triage_routes_lines(model))
    assert "security" in text and "gpt-9" in text
    assert "workspace-write" in text and "nit" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_loop_view.py -k triage_routes -q`
Expected: FAIL with `AttributeError: module 'code_review_loop.tui_loop_state' has no attribute 'triage_routes_lines'`.

- [ ] **Step 3: Write the implementation**

Append to `src/code_review_loop/tui_loop_state.py`:

```python
def triage_routes_lines(source: "Any") -> tuple[str, ...]:
    profile = _source_profile(source)
    routing = profile.triage.routing
    if not routing.enabled:
        return ()
    header = (
        f"    routing   default ‹ {routing.default_route} ›   "
        f"strict ‹ {'on' if routing.strict_on_unavailable_route else 'off'} ›   "
        f"escalate-model ‹ {'on' if routing.allow_model_escalation else 'off'} ›"
    )
    lines = [header, "    routes:"]
    for name, route in sorted(profile.triage.routes.items()):
        prefix = f"triage.routes.{name}"
        harness = _effective_value(source, f"{prefix}.harness", route.harness)
        model = _effective_value(source, f"{prefix}.model", route.model)
        reasoning_effort = _effective_value(
            source, f"{prefix}.reasoning_effort", route.reasoning_effort
        )
        timeout_seconds = _effective_value(
            source, f"{prefix}.timeout_seconds", route.timeout_seconds
        )
        sandbox = _effective_value(source, f"{prefix}.sandbox", route.sandbox)
        fallback = _effective_value(source, f"{prefix}.fallback", route.fallback)
        effort = harnesses.phase_effort_text(
            harness if isinstance(harness, str) else None,
            reasoning_effort if isinstance(reasoning_effort, str) else None,
        ) or "-"
        timeout = (
            f"{float(timeout_seconds):g}s" if timeout_seconds is not None else "-"
        )
        lines.append(
            f"      {name}  {harness} · {model or '-'} · {effort} · "
            f"{timeout} · {sandbox} · {fallback or 'drop'}"
        )
    return tuple(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_loop_view.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_loop_state.py tests/test_tui_loop_view.py
git commit -m "feat(tui): add triage routes table view-model"
```

---

## Task 4: Real Loop widgets + mount into the app (with Loop-first nav)

The interactive layer: lazy Textual widgets that consume Tasks 2–3, own focus/selection/inline-edit, and mount into the Loop workspace. Reorder nav to Loop-first.

**Files:**
- Create: `src/code_review_loop/tui_loop_widgets.py`
- Modify: `src/code_review_loop/tui.py`
- Test: `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `LoopEditModel` (Task 1); `tui_loop_state` loop view-models (Tasks 2–3); `harnesses.HARNESS_REGISTRY` implemented harness names + effort choices.
- Produces:
  - `loop_diagram_class() -> type | None` — lazy factory returning the `LoopDiagram` widget class (or `None` when Textual is unavailable), mirroring `tui.text_prompt_screen_class()`.
  - `HARNESS_CHOICES: tuple[str, ...]`, `EFFORT_CHOICES: tuple[str, ...]` — cycle orders for inline enum editing.
  - `phase_card_class() -> type | None`, `triage_routes_table_class() -> type | None`, and `loop_diagram_class() -> type | None` lazy factories. `LoopDiagram` must compose real child widgets for `PhaseCard` and, when triage is focused, `TriageRoutesTable`; do not collapse the whole screen into one `Static` text dump.
  - `LoopDiagram` widget: constructed with a `LoopEditModel`; renders header + per-phase `PhaseCard`s + rails + `TriageRoutesTable` (when triage focused); attributes `focused_index: int`, `expanded: bool`; methods `current_phase()`, `move(delta)`, `toggle_enabled()`, `cycle_field(key)`, `set_text_field(key, value)`, `set_loop_meta_field(key, value)`, `toggle_final_review()`, `rebuild()`. Exposes `is_dirty` (delegates to model).

- [ ] **Step 1: Write the failing pilot tests**

Append to `tests/test_tui_pilot_smoke.py` (it already imports `asyncio`, `tui`, and `pilot_app`; add `tui_loop_state` if it is not already imported):

```python
def test_loop_workspace_renders_real_diagram_widgets(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("1")  # Loop workspace (Loop-first nav)
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            assert app.query(".phase-card")
            rendered = str(diagram.render())
            assert "review" in rendered
            assert "remediation" in rendered
            assert "base" in rendered  # loop header meta

    asyncio.run(run())


def test_loop_inline_edit_marks_dirty_and_overlays(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n[profiles.edit.review]\n"
            "harness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.cycle_field("harness")  # review is focused_index 0
            await pilot.pause()
            assert diagram.is_dirty is True
            status = app.query_one("#status-bar")
            assert "*" in str(status.render())
            diagram.set_text_field("model", "gpt-5.6")
            diagram.set_text_field("timeout", "123")
            assert diagram.model.field_value("review.model", "gpt-5.5") == "gpt-5.6"
            assert diagram.model.field_value("review.timeout_seconds", None) == 123.0

    asyncio.run(run())


def test_loop_reverted_edit_clears_dirty_marker(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n[profiles.edit.review]\n"
            "harness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "gpt-5.6")
            app._update_console_status()
            assert "*" in str(app.query_one("#status-bar").render())
            diagram.set_text_field("model", "gpt-5.5")
            app._update_console_status()
            assert diagram.is_dirty is False
            assert "*" not in str(app.query_one("#status-bar").render())

    asyncio.run(run())
```

Add a focused triage-widget assertion:

```python
def test_loop_triage_focus_mounts_routes_table(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n[profiles.edit.triage]\nenabled=true\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='codex-midi'\n"
            "[profiles.edit.triage.routes.codex-midi]\nharness='codex'\nmodel='gpt-5.4-mini'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.press("down")
            await pilot.pause()
            assert app.query(".triage-routes-table")

    asyncio.run(run())


def test_loop_diagram_current_phase_clamps_index(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 999
            assert diagram.current_phase() == "commit"
            assert diagram.focused_index == len(tui_loop_state.LOOP_PHASES) - 1

    asyncio.run(run())
```

Also update the existing nav assertion in `test_tui_pilot_boots_home_view`: the home view's workspace tabs change from `1 Profiles` to `1 Loop` and `3 Profiles` under Loop-first nav. Replace `assert "1 Profiles" in rendered` with:

```python
assert "1 Loop" in rendered
assert "3 Profiles" in rendered
```

Add a direct unit assertion for the workspace order in `tests/test_tui.py`:

```python
def test_workspace_order_is_loop_first():
    assert tui._WORKSPACES == ("loop", "run", "profiles", "prompts")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k "loop_workspace or loop_inline" -q`
Expected: FAIL — `#loop-diagram` widget not found.

- [ ] **Step 3: Write the widget module**

Create `src/code_review_loop/tui_loop_widgets.py` with this contract:

- Importing the module must not import Textual; all Textual imports stay inside lazy factory functions.
- Provide `phase_card_class()`, `triage_routes_table_class()`, and `loop_diagram_class()` factories. Cache classes after the first successful factory call, mirroring `tui.text_prompt_screen_class()`.
- `PhaseCard` is a focusable/renderable widget with CSS class `phase-card`; it consumes `tui_loop_state.phase_card_lines(...)` and exposes update/rebuild hooks used by `LoopDiagram`.
- `TriageRoutesTable` is a renderable widget with CSS class `triage-routes-table`; it consumes `tui_loop_state.triage_routes_lines(model)` and is mounted only when triage is focused and routing is enabled.
- `LoopDiagram` owns selection state (`focused_index`, `expanded`) and composes one `PhaseCard` per phase plus a `TriageRoutesTable` child when appropriate. It may render rails/header itself, but phase bodies must be child widgets, not concatenated into a single `Static` text blob. Header and rails must call `tui_loop_state.loop_header_text(self.model)` and `tui_loop_state.loop_rail_meta(self.model)`, not `self.model.profile`, so unsaved metadata edits render immediately.
- Define `HARNESS_CHOICES` in `tui_loop_widgets.py` from `harnesses.HARNESS_REGISTRY` filtered to implemented harnesses (stable-sorted by key, with `codex` first if present). Do not hardcode a stale harness list.
- Define `EFFORT_CHOICES = profiles.REASONING_EFFORT_CHOICES` in `tui_loop_widgets.py`. Do not invent an effort list that can drift from the profile parser.
- Implement `current_phase()`, `toggle_enabled()`, `cycle_field(key)`, `set_text_field(key, value)`, `set_loop_meta_field(key, value)`, `toggle_final_review()`, `move(delta)`, and `rebuild()` against raw dotted keys from `tui_loop_state.PHASE_DOTTED` / `LOOP_META_DOTTED`. `current_phase()` clamps `focused_index` into range and returns `tui_loop_state.LOOP_PHASES[self.focused_index]`.
- Preserve optional dependency behavior: if Textual is unavailable, all factories return `None`.

- [ ] **Step 4: Mount the widget and reorder nav in `tui.py`**

Make these edits in `src/code_review_loop/tui.py`:

1. **Reorder nav.** Change `_WORKSPACES` to `("loop", "run", "profiles", "prompts")`. In `_build_bindings`, change the four workspace bindings so Loop is `1` and the others follow the design order `1 Loop · 2 Run · 3 Profiles · 4 Prompts`:

```python
        ("1", "workspace_loop", "Loop"),
        ("2", "workspace_run", "Run"),
        ("3", "workspace_profiles", "Profiles"),
        ("4", "workspace_prompts", "Prompts"),
```

2. **Reorder the tab labels.** In `_workspace_tabs_markup`, change `labels` to:

```python
    labels = (
        ("loop", "1 Loop"),
        ("run", "2 Run"),
        ("profiles", "3 Profiles"),
        ("prompts", "4 Prompts"),
    )
```

3. **Default to the Loop workspace.** In `_RevRemAppMixin.__init__`, change `self._workspace: str = "profiles"` to `self._workspace: str = "loop"`.

4. **Compose the diagram.** In `compose`, inside the `with _Horizontal(id="body"):` block, add a third child after the right pane that holds the diagram when Textual containers are available:

```python
                loop_cls = _loop_diagram_widget(self)
                if loop_cls is not None and _Vertical is not None:
                    with _Vertical(id="loop-pane"):
                        yield loop_cls
```

5. **Add the helper + display toggling.** Add module-level helpers near `_panel_widget`:

```python
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
```

In `__init__`, initialise `self._loop_diagram = None` and `self._loop_model = None`.

6. **Toggle panes by workspace.** In `_render_workbench`, after the existing updates, toggle visibility so the Loop pane shows only on the Loop workspace and the two text panes hide then:

```python
        _set_widget_display(self, "#loop-pane", self._workspace == "loop")
        _set_widget_display(self, "#left-pane", self._workspace != "loop")
        _set_widget_display(self, "#right-pane", self._workspace != "loop")
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.rebuild()
```

Add the helper:

```python
def _set_widget_display(app: Any, selector: str, visible: bool) -> None:
    widget = _resolve_widget(app, selector)
    if widget is not None:
        widget.display = visible
```

7. **Route phase navigation + edit keys to the diagram.** In `_move_selection`, when `self._workspace == "loop"` and the diagram exists, delegate:

```python
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.move(delta)
            self._update_console_status()
            return
```

(Place this branch before the existing `loop`/`prompts`/`run` phase-index branch.)

8. **Add edit-key actions + bindings.** Add bindings in `_build_bindings` (alongside the others):

```python
        ("space", "toggle_phase", "Toggle phase"),
        ("m", "cycle_harness", "Harness"),
        ("f", "cycle_effort", "Effort"),
        ("M", "edit_model", "Model"),
        ("i", "edit_max_iterations", "Max iterations"),
        ("F", "toggle_final_review", "Final review"),
        ("t", "edit_timeout", "Timeout"),
```

and the actions on `_RevRemAppMixin`:

```python
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
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._open_loop_meta_prompt("max_iterations")

    def action_toggle_final_review(self) -> None:
        if self._workspace == "loop" and self._loop_diagram is not None:
            self._loop_diagram.toggle_final_review()
            self._update_console_status()
```

Implement `_open_loop_text_field_prompt(field)` using the existing prompt-entry infrastructure rather than adding a new Textual dependency path. The callback must call `self._loop_diagram.set_text_field(field, value)`, rebuild the diagram, update the dirty status marker, and leave save-time validation to `LoopEditModel.save()`.

Implement `_open_loop_meta_prompt(field)` the same way, calling `self._loop_diagram.set_loop_meta_field(field, value)`.

9. **Update contextual footer hints.** In the existing `_footer_markup`, replace the old Loop footer with focus-aware hints from the active `LoopDiagram`. At minimum:

```python
elif app._workspace == "loop":
    phase = (
        app._loop_diagram.current_phase()
        if getattr(app, "_loop_diagram", None) is not None
        else "review"
    )
    route_keys = " [Enter]edit route [a]add route" if phase == "triage" else ""
    keys = (
        "[up/down]phase [Enter]expand [space]toggle [m]harness [f]effort "
        "[M]model [t]timeout [i]iterations [F]final-review "
        f"[s]save [r]run{route_keys} [?]help"
    )
```

The footer should show only actions that are meaningful in the current workspace; keep the existing help overlay path when `app._help_visible` is true.

10. **Show the dirty marker.** In `_status_bar_markup`, compute a dirty suffix and append it to the profile name:

```python
    dirty = "*" if getattr(app, "_loop_diagram", None) is not None and app._loop_diagram.is_dirty else ""
```

and change the `profile=` fragment to `profile={tui_state.markup_escape(profile_name)}{dirty}`.

11. **Add CSS for the loop pane.** In `_RevRemAppMixin.CSS`, add:

```css
    #loop-pane {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }
```

- [ ] **Step 5: Run the new pilot tests**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -q`
Expected: PASS (existing + new cases).

- [ ] **Step 6: Run the full TUI suite (no regressions)**

Run: `python -m pytest tests/test_tui.py tests/test_tui_pilot_smoke.py tests/test_tui_state.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): mount interactive loop diagram; loop-first nav"
```

---

## Task 4b: LoopDiagram SVG snapshot coverage

Lock the showcase-facing rendered output promised by REVREM-DESIGN-001 §8. These snapshots are not a substitute for the pilot interaction tests; they are a visual regression suite and a source of demo artifacts.

**Files:**
- Create: `tests/test_tui_loop_snapshots.py`

**Requirements:**
- Add `pytest-textual-snapshot` to the `dev` optional dependency group in `pyproject.toml` if no equivalent SVG snapshot helper already exists; do **not** add it to the runtime `[tui]` extra. Use the repo's Textual snapshot mechanism if available (`pytest-textual-snapshot` / SVG export). If the dependency is still absent in the current environment, add a guarded skip and a TODO in the test file rather than replacing snapshots with string-only assertions.
- Capture at least these `LoopDiagram` states:
  - triage disabled, `runtime.inner_check_retries = 0`, `pipeline.final_review = false`;
  - triage enabled with at least two routes and a default route;
  - `runtime.inner_check_retries = 2` so the inner remediation/check rail is visible;
  - `pipeline.final_review = true` so the final-review row is visible.
- Run each snapshot at a stable terminal size (`120x40` minimum; add `80x24` smoke if the widget supports compact layout).
- Store snapshots in the existing snapshot location used by the project or under `tests/snapshots/tui_loop/`; do not commit transient terminal recordings.

Run: `python -m pytest tests/test_tui_loop_snapshots.py -q`
Expected: PASS with committed snapshots or SKIP only when the snapshot dependency is not installed.

- [ ] **Commit**

```bash
git add tests/test_tui_loop_snapshots.py tests/snapshots
git commit -m "test(tui): snapshot loop diagram states"
```

---

## Task 5: Save → profile, save-and-run, and dirty guard

Wire the explicit Save and the save-and-run path, and lock the persisted-edit ⇄ CLI-equivalence guarantee end-to-end.

**Files:**
- Modify: `src/code_review_loop/tui.py`
- Test: `tests/test_tui_pilot_smoke.py`, `tests/test_tui_cli_equivalence.py`

**Interfaces:**
- Consumes: `LoopDiagram.model.save()` (Task 1); existing `action_launch_run` (Task wiring).
- Produces: `action_save_loop` on the app; save-and-run behaviour when the working copy is dirty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_pilot_smoke.py`:

```python
def test_loop_save_persists_and_clears_dirty(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n[profiles.edit.review]\n"
            "harness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.model.set_field("review.model", "gpt-5.6")
            diagram.rebuild()
            assert diagram.is_dirty is True
            app.action_save_loop()
            await pilot.pause()
            assert diagram.is_dirty is False
            persisted = (repo / ".revrem.toml").read_text(encoding="utf-8")
            assert "gpt-5.6" in persisted

    asyncio.run(run())
```

Add two guards to `tests/test_tui_cli_equivalence.py`.

First, keep the cheap launch-plan assertion so the TUI still launches by profile name rather than expanding edited settings into argv:

```python
def test_loop_save_keeps_launch_plan_cli_equivalent(tmp_path):
    from code_review_loop import profiles, tui_state
    from code_review_loop.tui_loop_model import LoopEditModel

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n[profiles.edit.review]\nmodel='gpt-5.5'\n",
        encoding="utf-8",
    )
    model = LoopEditModel.load("edit", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.save()
    profile = profiles.resolve_profile("edit", cwd=repo, require_implemented=False)
    plan = tui_state.launch_plan(profile, dry_run=False)
    assert plan.argv == ("revrem", "--profile", "edit")
```

Second, add an end-to-end fake-harness parity test that meets REVREM-DESIGN-001 §8's artifact-equivalence bar:

```python
def test_loop_save_run_artifacts_match_cli_set_run(tmp_path):
    from support.run_artifact_compare import assert_equivalent_run_artifacts
    from code_review_loop import profiles
    from code_review_loop.tui_loop_model import LoopEditModel

    repo_model = _repo_with_fake_harness_profile(tmp_path / "via_model")
    repo_cli = _repo_with_fake_harness_profile(tmp_path / "via_cli")

    model = LoopEditModel.load("edit", cwd=repo_model)
    model.set_field("review.model", "fake-review-model")
    model.save()
    profiles.set_profile_field("edit", "review.model", "fake-review-model", cwd=repo_cli)

    model_run = _run_revrem_profile(repo_model, "edit")
    cli_run = _run_revrem_profile(repo_cli, "edit")
    assert_equivalent_run_artifacts(model_run, cli_run)
```

Use the existing fake-harness helpers from `test_tui_cli_equivalence.py`; if they are local to another module, promote only the minimal helper to `tests/support/`. This test proves a working-copy save feeds the same runtime behavior as the equivalent CLI config edit, not just the same launch argv.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k loop_save tests/test_tui_cli_equivalence.py -k loop_save -q`
Expected: FAIL — `action_save_loop` not defined.

- [ ] **Step 3: Implement Save + save-and-run + binding**

In `src/code_review_loop/tui.py`:

1. Add the binding in `_build_bindings`:

```python
        ("s", "save_loop", "Save loop"),
```

Note: this **replaces** the existing `("s", "show_profile", "Show")` binding only when on the Loop workspace; keep `show_profile` reachable from the Profiles workspace by leaving its action method in place and dispatching by workspace inside `action_save_loop` (below). To avoid a double-bound key, change the existing `("s", "show_profile", "Show")` entry to be dispatched through the new `action_save_loop`.

2. Extend `_notify(app, message)` to accept an optional keyword-only `severity: str = "information"` and pass it through to Textual's notification mechanism when available. If the current environment lacks severity support, preserve the old message-only behavior but add a visible prefix (`"Saved: ..."` / `"Save failed: ..."`). Save success and save failure must be visually distinguishable in the TUI and in tests.

3. Add the action:

```python
    def action_save_loop(self) -> None:
        if self._workspace != "loop" or self._loop_diagram is None:
            # Preserve prior behaviour on other workspaces.
            self.action_show_profile()
            return
        if not self._loop_diagram.is_dirty:
            _notify(self, "No unsaved loop changes.")
            return
        try:
            path = self._loop_diagram.model.save()
        except (OSError, ValueError) as exc:
            _notify(self, f"Save failed: {exc}", severity="error")
            return
        self._refresh_profiles_from_disk()
        # Re-point the diagram at the refreshed model.
        self._render_workbench()
        _notify(self, f"Saved loop to {path}", severity="information")
        self._update_console_status()
```

4. Make Run save-first when dirty. In `action_launch_run`, immediately after resolving `selected`/`profile_name` and before building the plan, add:

```python
        if (
            self._workspace == "loop"
            and self._loop_diagram is not None
            and self._loop_diagram.is_dirty
        ):
            try:
                self._loop_diagram.model.save()
            except (OSError, ValueError) as exc:
                _notify(self, f"Save-and-run aborted: {exc}", severity="error")
                return
            self._refresh_profiles_from_disk()
            _notify(self, f"Saved loop before run: {profile_name}", severity="information")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k loop_save -q tests/test_tui_cli_equivalence.py -q`
Expected: PASS.

- [ ] **Step 5: Run the repository gate**

Run: `./scripts/dev-check`
Expected: PASS (pytest, lint, type, consistency, and Meminit gates clean except for any pre-existing documented warning).

- [ ] **Step 6: Commit**

```bash
git add src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py tests/test_tui_cli_equivalence.py
git commit -m "feat(tui): explicit Save and save-and-run for the loop working copy"
```

---

## Task 6: Documentation + changelog + final verification

**Files:**
- Modify: `docs/70-devex/devex-001-using-code-review-loop.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document the Loop screen**

In `docs/70-devex/devex-001-using-code-review-loop.md`, replace the existing pre-overhaul TUI section with the new Loop-first workbench description. Do not add a second conflicting subsection. Include: keys `↑/↓` move phase, `Enter` expand/collapse, `space` toggle a phase, `m` cycle harness, `f` cycle effort, `M` edit model, `t` edit timeout, `i` edit max iterations, `F` toggle final review, `s` save loop to its profile, `r` run (save-and-run when dirty); the `*` next to the profile name means unsaved working-copy changes; the diagram is config-truthful (inner rail only when `runtime.inner_check_retries > 0`, final review only when enabled); triage routes are shown read-only (route editing arrives in Plan 4).

Add a regression test to the existing TUI state tests that calls `tui_state.render_shell_text()` for a profile with triage enabled, at least one route, `runtime.inner_check_retries > 0`, and `pipeline.final_review = true`; assert the result is non-empty and includes the selected profile name plus loop/phase content. This locks the no-Textual fallback after the new `tui_loop_state` functions are added.

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, under the Unreleased section, add:

```
### Added
- TUI: interactive Loop workspace — a config-truthful vertical loop diagram with
  in-loop editing of harness / model / effort / timeout / enable and explicit
  Save (working copy + save-to-profile), built on real Textual widgets.
```

- [ ] **Step 3: Final full-suite run + lint/format gate**

Run: `./scripts/dev-check`
Expected: PASS (pytest, lint, type, consistency, and Meminit gates clean except for any pre-existing documented warning).

- [ ] **Step 4: Commit**

```bash
git add docs/70-devex/devex-001-using-code-review-loop.md CHANGELOG.md
git commit -m "docs(tui): document the interactive loop workspace"
```

---

## Self-review (run by the plan author before execution)

**Spec coverage (REVREM-DESIGN-001 §5.1, §6):**
- Vertical accordion diagram → Task 4 `LoopDiagram.diagram_lines` (header + per-phase + rails). ✓
- `●/○` enabled/disabled, space toggles → `PHASE_ENABLED_GLYPH`/`PHASE_DISABLED_GLYPH` (Task 2) + `toggle_enabled` (Task 4). ✓
- Config-truthful rails (inner only when retries>0, final review only when on, disabled drop out) → `loop_rail_meta` (Task 2), tested. ✓
- Working-copy overlays on all authoring views → `loop_header_text(model)`, `loop_rail_meta(model)`, and `triage_routes_lines(model)` reflect unsaved meta/route edits before Save (Tasks 2–3), tested. ✓
- Inline single-field edit (harness/model/effort/timeout) → cycle (`m`/`f`) + text-entry actions (`M`/`t`) + `set_text_field` (Task 4); model/timeout free-text validated at Save (Global Constraints). ✓
- Triage routes table (read-only here) → `triage_routes_lines` (Task 3); route-row modal deferred to Plan 4 (stated). ✓
- Triage structural fields scoped deliberately: `triage.prompt` is Plan 4, `triage.contract` and `triage.routing.mode` are structural setup fields, and `triage.on_invalid` remains out of Plan 2's inline edit surface unless a later plan adds a dedicated control. ✓
- Working copy + explicit save → `LoopEditModel` (Task 1) + `action_save_loop` / save-and-run (Task 5). Dirty state is semantic, so no-op/reverted edits clear `edits` and remove the `*` marker. ✓
- CLI-equivalence preserved → `test_save_round_trips_to_config_set_path` (Task 1) + launch-plan guard + `assert_equivalent_run_artifacts` fake-harness run parity (Task 5) + full `test_tui_cli_equivalence.py`. ✓
- Real interactive widgets consuming view-models; `render_shell_text` retained as fallback (untouched). ✓
- Stale design §4.2 corrected → Task 1 Step 0. ✓
- Loop-first nav → Task 4 (with pilot assertion updates). ✓

**Placeholder scan:** No TBD/TODO. Test steps show concrete tests. Implementation steps are either paste-ready pure-function snippets or explicit contracts where paste-ready widget code would be misleading; the widget task is acceptance-test driven by real child-widget queries.

**Type consistency:** `field_value(dotted_key, fallback)` signature is identical across Tasks 1, 2, 4. `tui_loop_state.PHASE_DOTTED`, `LOOP_META_DOTTED`, `LOOP_PHASES`, `loop_rail_meta`, `phase_card_lines`, `triage_routes_lines`, `phase_gutter`, `loop_header_text`, and `LoopDiagram.current_phase()` names match between definition (Tasks 2–4) and use (Plan 4). `loop_diagram_class()` returns the class used by `_loop_diagram_widget`. `commit` edits target raw `commit.message_model` (not `commit.model`), matching `CommitConfig`; loop meta edits target raw `pipeline.max_iterations` / `pipeline.final_review` through `i` / `F`, while `M` remains model editing.

**Raw-key guard scan:** before executing Task 1 and again before final review, run `rg -n 'top-level raw-key|raw top-level|profile root|set_field\("max_iterations|set_field\("final_review|field_value\("max_iterations|field_value\("final_review|== "max_iterations"|== "final_review"|root-level max_iterations|root-level final_review|raw profile keys are max_iterations|fake pipeline' docs/05-planning/plan-010-tui-overhaul-loop-screen.md`. Any hit must be intentionally reviewed; loop metadata belongs under `[profiles.<name>.pipeline]`.

**Known risk to watch in review:** Textual widget composition can regress the optional-dependency contract. Confirm `import code_review_loop.tui_loop_widgets` succeeds without Textual installed, and keep all Textual imports inside lazy factories.
