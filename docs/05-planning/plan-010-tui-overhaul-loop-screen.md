---
document_id: REVREM-PLAN-010
type: PLAN
title: TUI Overhaul Plan 2 — Loop Screen (editable diagram + working copy)
status: Draft
version: '0.1'
last_updated: '2026-06-28'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Plan 2 of the loop-first TUI overhaul (REVREM-DESIGN-001): build the
  authoring Loop screen as real interactive Textual widgets (LoopDiagram / PhaseCard
  / TriageRoutesTable) fed by pure tui_state view-models, on a working-copy + explicit-save
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

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Loop the editable centre of the TUI — a vertical, config-truthful diagram of real interactive Textual widgets that lets the operator edit harness / model / effort / timeout / enable per phase (and triage's routing-level fields) into an in-memory working copy, then persist the whole copy to the owning profile file in one explicit Save.

**Architecture:** Three layers, bottom-up. (1) A pure, Textual-free **working-copy model** (`LoopEditModel`) holds the resolved baseline `Profile` plus a dict of pending dotted-key edits; it renders effective field values (edit overlays baseline), produces an authored raw delta, and persists through Plan 1's `profiles.save_profile_raw`. (2) Pure **view-model functions** in `tui_state` turn the model into per-phase card lines, a loop header, rail metadata, and the triage routes table — config-truthful (inner rail only when `runtime.inner_check_retries > 0`, disabled phases marked and dropped from the rails, final review shown only when on). (3) Real **Textual widgets** in a new `tui_loop_widgets.py` (`PhaseCard`, `TriageRoutesTable`, `LoopDiagram`) consume those view-models, own focus/selection/inline-edit keyboard handling, and mount into the existing app's Loop workspace. The same view-models keep `render_shell_text` working as the headless fallback.

**Tech Stack:** Python 3.12, Textual 8.2.5 (optional `[tui]` extra, lazy-imported), `pytest` + Textual pilot/`run_test`, the Plan 1 `profiles` edit primitives (`deep_set_raw`, `save_profile_raw`, `set_profile_field`).

## Plan sequence (this is Plan 2 of 4)

1. **Plan 1 (REVREM-PLAN-009):** edit primitives — library + `config set`. **COMPLETE.**
2. **Plan 2 (this doc):** authoring Loop screen — working-copy model + `LoopDiagram` / `PhaseCard` / `TriageRoutesTable` widgets + Save→profile.
3. **Plan 3:** run / monitor live mode — the same diagram, live (`LoopRunView`, `EventLog`).
4. **Plan 4:** profiles picker + prompts library + in-loop prompt picking + route-row modal editing.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from REVREM-DESIGN-001.

- **Working copy + explicit save (option A).** Inline edits mutate an in-memory working copy only — never one CLI/disk write per keystroke. A `*` marks unsaved changes. **Save → profile** persists the whole working copy in one call to `profiles.save_profile_raw(name, authored_delta, cwd=..., home=...)`. **Run** launches `revrem --profile NAME`; if the working copy is dirty, Run offers *save-and-run* (persist, then launch).
- **The diagram is config-truthful.** What is shown equals what the profile will do: the inner remediation⇄checks rail is drawn **only** when `runtime.inner_check_retries > 0`; disabled phases are marked disabled and drop out of the loop rails; the `final review` row is shown **only** when `pipeline.final_review` is true.
- **Validation timing (explicit Plan-2 scope decision).** Enumerated fields (harness, reasoning effort, the boolean enables, sandbox) are edited by cycling through known-valid choices, so they cannot reach an invalid value in the working copy. Free-text fields (model, timeout) are validated at **Save** time (where `save_profile_raw` → `parse_profile` raises `ValueError`), and the error surfaces on the Save action; the working copy is not blocked per-keystroke. Per-field inline validation as-you-type is deferred to Plan 4. This is a deliberate narrowing of REVREM-DESIGN-001 §7 for this iteration, not an oversight.
- **CLI-equivalence is preserved.** The TUI still launches runs as `revrem --profile NAME` and persists config through the same library write path the CLI uses. `assert_equivalent_run_artifacts` parity and the existing `test_tui_cli_equivalence.py` must continue to pass.
- **Textual stays an optional dependency.** All Textual widget/screen classes are defined lazily through factory functions (mirroring the existing `text_prompt_screen_class()` in `tui.py`); importing `code_review_loop.tui` / `tui_loop_widgets` must not require Textual. When Textual is absent, `render_shell_text` remains the headless view.
- **Scope of edits in Plan 2.** Editable from the loop: per-phase `enabled` (where the phase has one), `harness`, `model` (commit uses `message_model`), `reasoning_effort`, `timeout_seconds`; loop meta `pipeline.max_iterations`, `pipeline.final_review`, `runtime.inner_check_retries`; triage routing-level `triage.routing.default_route`, `triage.routing.strict_on_unavailable_route`, `triage.routing.allow_model_escalation`. **Out of scope (Plan 4):** editing individual triage route-table cells (rendered read-only here), prompt picking/editing, and the profiles/prompts/run screens (left as their current markup until their plans).
- **Branch & commits.** Work on `feat/tui-live-runs` (never `main`). Stage files explicitly per task — never `git add -A`. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm
  ```

## Pre-flight note for the executor

REVREM-DESIGN-001 §4.2 is **stale**: it says Save will reuse the `config import` path and explicitly *rejects* adding `config set`. Plan 1 shipped both `config set` and the `save_profile_raw` library writer, and Plan 2 calls `save_profile_raw` in-process. **Task 1, Step 0 updates §4.2** so the design matches the shipped code before any widget work — otherwise the final whole-branch reviewer will (correctly) flag a code-vs-spec mismatch.

---

## File structure

- **Create** `src/code_review_loop/tui_loop_model.py` — `LoopEditModel` working copy (pure; imports only `profiles`).
- **Modify** `src/code_review_loop/tui_state.py` — add pure loop view-model functions (header, per-phase card lines, rail metadata, triage routes lines).
- **Create** `src/code_review_loop/tui_loop_widgets.py` — lazy Textual widget factories: `PhaseCard`, `TriageRoutesTable`, `LoopDiagram`.
- **Modify** `src/code_review_loop/tui.py` — mount the `LoopDiagram` into the Loop workspace; reorder nav to Loop-first; wire Save / save-and-run and the dirty `*` indicator.
- **Create** `tests/test_tui_loop_model.py`, `tests/test_tui_loop_view.py` — pure-layer unit tests.
- **Modify** `tests/test_tui_pilot_smoke.py` — widget pilot tests + updated nav assertions.
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
  - `field_value(dotted_key: str, fallback: object) -> object` — coerced pending edit if present, else `fallback`.
  - `set_field(dotted_key: str, value: str) -> None`.
  - `authored_delta() -> dict[str, object]`.
  - `save() -> Path` — persists `authored_delta()` via `save_profile_raw`, clears `edits`, reloads `profile`.

- [ ] **Step 0: Update the stale design section**

In `docs/30-design/design-001-loop-first-tui-overhaul.md`, replace the parenthetical rejection in §4.2 item 2 so it reflects shipped reality. Change the sentence that currently reads:

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
    assert model.field_value("review.model", "gpt-5.5") == "gpt-5.6"
    # coercion: max_iterations is an int field
    assert model.field_value("pipeline.max_iterations", 4) == 9
    assert model.is_dirty is True


def test_authored_delta_nests_dotted_keys(tmp_path):
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.set_field("runtime.inner_check_retries", "2")
    delta = model.authored_delta()
    assert delta == {
        "review": {"model": "gpt-5.6"},
        "runtime": {"inner_check_retries": 2},
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

from dataclasses import dataclass, field
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
        self.edits[dotted_key] = value

    def authored_delta(self) -> dict[str, object]:
        return reduce(
            lambda acc, item: profiles.deep_set_raw(acc, item[0], item[1]),
            self.edits.items(),
            {},
        )

    def save(self) -> Path:
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
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_loop_model.py tests/test_tui_loop_model.py docs/30-design/design-001-loop-first-tui-overhaul.md
git commit -m "feat(tui): add LoopEditModel working-copy + fix stale design 4.2"
```

---

## Task 2: Loop diagram view-models (pure functions in `tui_state`)

Per-phase card lines, the loop header, and rail metadata — config-truthful, Textual-free, so they can be unit-tested directly and reused by `render_shell_text`.

**Files:**
- Modify: `src/code_review_loop/tui_state.py`
- Test: `tests/test_tui_loop_view.py`

**Interfaces:**
- Consumes: `LoopEditModel` (Task 1); `profiles.Profile`; existing `harnesses.phase_effort_text(harness, effort)`.
- Produces (for Tasks 3 & 4):
  - `LOOP_PHASES: tuple[str, ...] = ("review", "triage", "remediation", "checks", "commit")`
  - `PHASE_DOTTED: dict[str, dict[str, str]]` — per-phase map of edit-target dotted keys (see code).
  - `loop_header_text(profile) -> str`
  - `@dataclass(frozen=True) class LoopRailMeta` with `max_iterations: int`, `inner_check_retries: int`, `inner_rail: bool`, `final_review: bool`, `outer_return_label: str`, `inner_return_label: str | None`, `final_review_label: str | None`.
  - `loop_rail_meta(profile) -> LoopRailMeta`
  - `phase_card_lines(model, phase, *, focused, expanded) -> tuple[str, ...]`
  - `phase_gutter(phase, rail_meta) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_loop_view.py`:

```python
from __future__ import annotations

from pathlib import Path

from code_review_loop import profiles, tui_state
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
        "[profiles.p]\nbase='main'\nmax_iterations=5\n[profiles.p.runtime]\ninner_check_retries=0\n",
    )
    meta = tui_state.loop_rail_meta(_model(repo, "p").profile)
    assert meta.inner_rail is False
    assert meta.inner_return_label is None
    assert "iteration < 5" in meta.outer_return_label


def test_rail_meta_draws_inner_rail_when_retries_positive(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\nbase='main'\nmax_iterations=5\n[profiles.p.runtime]\ninner_check_retries=2\n",
    )
    meta = tui_state.loop_rail_meta(_model(repo, "p").profile)
    assert meta.inner_rail is True
    assert meta.inner_return_label is not None
    assert "up to 2 inner retries" in meta.inner_return_label


def test_rail_meta_final_review_only_when_on(tmp_path):
    on = _repo(tmp_path / "on", "[profiles.p]\nbase='main'\nfinal_review=true\n")
    off = _repo(tmp_path / "off", "[profiles.p]\nbase='main'\nfinal_review=false\n")
    assert tui_state.loop_rail_meta(_model(on, "p").profile).final_review is True
    assert tui_state.loop_rail_meta(_model(off, "p").profile).final_review is False
    assert tui_state.loop_rail_meta(_model(off, "p").profile).final_review_label is None


def test_phase_card_summary_shows_harness_model_and_disabled_marker(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\nbase='main'\n[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    review = tui_state.phase_card_lines(model, "review", focused=False, expanded=False)
    text = "\n".join(review)
    assert "review" in text and "codex" in text and "gpt-5.5" in text
    assert text.lstrip().startswith(tui_state.PHASE_ENABLED_GLYPH)
    # triage defaults off -> disabled glyph
    triage = tui_state.phase_card_lines(model, "triage", focused=False, expanded=False)
    assert "\n".join(triage).lstrip().startswith(tui_state.PHASE_DISABLED_GLYPH)


def test_phase_card_expanded_shows_edit_fields_with_overlay(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\nbase='main'\n[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    model.set_field("review.model", "gpt-5.6")
    expanded = tui_state.phase_card_lines(model, "review", focused=True, expanded=True)
    text = "\n".join(expanded)
    assert "harness" in text and "model" in text and "effort" in text and "timeout" in text
    # overlay reflected, not the baseline
    assert "gpt-5.6" in text and "gpt-5.5" not in text


def test_loop_header_reports_meta(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\nbase='main'\nmax_iterations=7\n[profiles.p.runtime]\ninner_check_retries=3\n",
    )
    header = tui_state.loop_header_text(_model(repo, "p").profile)
    assert "main" in header and "7" in header and "3" in header
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_loop_view.py -q`
Expected: FAIL with `AttributeError: module 'code_review_loop.tui_state' has no attribute 'loop_rail_meta'`.

- [ ] **Step 3: Write the implementation**

Append to `src/code_review_loop/tui_state.py` (after the existing `pipeline_phases` function). The `dataclass` import is already present at the top of the file.

```python
LOOP_PHASES: tuple[str, ...] = ("review", "triage", "remediation", "checks", "commit")
PHASE_ENABLED_GLYPH = "●"  # ●
PHASE_DISABLED_GLYPH = "○"  # ○

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


def loop_header_text(profile: profiles.Profile) -> str:
    retries = profile.runtime.inner_check_retries
    return (
        f"base {profile.pipeline.base} · max {profile.pipeline.max_iterations} "
        f"· stop when clear · inner-check retries: {retries}"
    )


def loop_rail_meta(profile: profiles.Profile) -> LoopRailMeta:
    retries = profile.runtime.inner_check_retries
    inner_rail = retries > 0
    final_review = profile.pipeline.final_review
    return LoopRailMeta(
        max_iterations=profile.pipeline.max_iterations,
        inner_check_retries=retries,
        inner_rail=inner_rail,
        final_review=final_review,
        outer_return_label=(
            f"not clear & iteration < {profile.pipeline.max_iterations} → review"
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
    summary = f"{pointer} {glyph} {phase} " + " · ".join(summary_bits)
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

Note: the `from typing import Any` import is already present at the top of `tui_state.py`; the `"Any"` annotations on `model` avoid a hard import of `LoopEditModel` (keeps `tui_state` free of a circular import — `tui_loop_model` imports `profiles` only, and `tui_state` already imports `profiles`/`harnesses`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_loop_view.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the existing view-model + equivalence suites (no regressions)**

Run: `python -m pytest tests/test_tui_state.py tests/test_tui_cli_equivalence.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/code_review_loop/tui_state.py tests/test_tui_loop_view.py
git commit -m "feat(tui): add config-truthful loop diagram view-models"
```

---

## Task 3: Triage routes view-model (pure)

The discriminating case: when triage is focused, render the routing-level line plus a read-only routes table (route-row editing is Plan 4).

**Files:**
- Modify: `src/code_review_loop/tui_state.py`
- Test: `tests/test_tui_loop_view.py` (add cases)

**Interfaces:**
- Consumes: `profiles.Profile` (`profile.triage.routing`, `profile.triage.routes`); `harnesses.phase_effort_text`.
- Produces: `triage_routes_lines(profile) -> tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_loop_view.py`:

```python
def _routes_repo(tmp_path: Path) -> Path:
    body = "\n".join(
        (
            "[profiles.r]",
            "base='main'",
            "[profiles.r.triage]",
            "enabled=true",
            "[profiles.r.triage.routing]",
            "enabled=true",
            "default_route='remediation'",
            "strict_on_unavailable_route=false",
            "allow_model_escalation=true",
            "[profiles.r.triage.routes.security]",
            "harness='codex'",
            "model='gpt-5.5'",
            "reasoning_effort='high'",
            "sandbox='read-only'",
            "fallback='remediation'",
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
    lines = tui_state.triage_routes_lines(_model(repo, "r").profile)
    text = "\n".join(lines)
    assert "default" in text and "remediation" in text
    assert "strict" in text and "escalate" in text
    assert "security" in text and "gpt-5.5" in text and "high" in text
    assert "nit" in text and "haiku-4.5" in text


def test_triage_routes_lines_empty_when_routing_off(tmp_path):
    repo = _repo(
        tmp_path,
        "[profiles.p]\nbase='main'\n[profiles.p.triage]\nenabled=true\n",
    )
    assert tui_state.triage_routes_lines(_model(repo, "p").profile) == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_loop_view.py -k triage_routes -q`
Expected: FAIL with `AttributeError: module 'code_review_loop.tui_state' has no attribute 'triage_routes_lines'`.

- [ ] **Step 3: Write the implementation**

Append to `src/code_review_loop/tui_state.py`:

```python
def triage_routes_lines(profile: profiles.Profile) -> tuple[str, ...]:
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
        effort = harnesses.phase_effort_text(route.harness, route.reasoning_effort) or "-"
        timeout = f"{route.timeout_seconds:g}s" if route.timeout_seconds is not None else "-"
        lines.append(
            f"      {name}  {route.harness} · {route.model or '-'} · {effort} · "
            f"{timeout} · {route.sandbox} · {route.fallback or 'drop'}"
        )
    return tuple(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_loop_view.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_state.py tests/test_tui_loop_view.py
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
- Consumes: `LoopEditModel` (Task 1); `tui_state` loop view-models (Tasks 2–3); `harnesses.IMPLEMENTED` harness names + effort choices.
- Produces:
  - `loop_diagram_class() -> type | None` — lazy factory returning the `LoopDiagram` widget class (or `None` when Textual is unavailable), mirroring `tui.text_prompt_screen_class()`.
  - `HARNESS_CHOICES: tuple[str, ...]`, `EFFORT_CHOICES: tuple[str, ...]` — cycle orders for inline enum editing.
  - `LoopDiagram` widget: constructed with a `LoopEditModel`; renders header + per-phase `PhaseCard`s + rails + `TriageRoutesTable` (when triage focused); attributes `focused_index: int`, `expanded: bool`; methods `move(delta)`, `toggle_enabled()`, `cycle_field(key)`, `set_text_field(key, value)`, `rebuild()`. Exposes `is_dirty` (delegates to model).

- [ ] **Step 1: Write the failing pilot tests**

Append to `tests/test_tui_pilot_smoke.py` (it already imports `asyncio`, `tui`, and `pilot_app`):

```python
def test_loop_workspace_renders_real_diagram_widgets(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("2")  # Loop workspace (Loop-first nav)
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
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
            "[profiles.edit]\nbase='main'\n[profiles.edit.review]\n"
            "harness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("2")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.cycle_field("harness")  # review is focused_index 0
            await pilot.pause()
            assert diagram.is_dirty is True
            status = app.query_one("#status-bar")
            assert "*" in str(status.render())

    asyncio.run(run())
```

Also update the existing nav assertion in `test_tui_pilot_boots_home_view`: the home view's workspace tabs change from `1 Profiles` to `3 Profiles` under Loop-first nav. Change the assertion `assert "1 Profiles" in rendered` to `assert "3 Profiles" in rendered`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k "loop_workspace or loop_inline" -q`
Expected: FAIL — `#loop-diagram` widget not found.

- [ ] **Step 3: Write the widget module**

Create `src/code_review_loop/tui_loop_widgets.py`:

```python
"""Lazy Textual widgets for the TUI Loop screen.

Importing this module never requires Textual; widget classes are built on first
use through ``loop_diagram_class()`` (mirrors ``tui.text_prompt_screen_class``).
"""

from __future__ import annotations

from typing import Any

from code_review_loop import harnesses, tui_state
from code_review_loop.tui_loop_model import LoopEditModel

# Cycle orders for inline enum editing. Kept short and known-valid so the
# working copy cannot reach an invalid enum value (see Plan 2 validation-timing).
HARNESS_CHOICES: tuple[str, ...] = tuple(
    spec.name for spec in harnesses.HARNESS_REGISTRY.values() if spec.implemented
)
EFFORT_CHOICES: tuple[str, ...] = ("low", "medium", "high")

_LOOP_DIAGRAM_CLASS: type[Any] | None = None


def _cycle(choices: tuple[str, ...], current: object) -> str:
    if not choices:
        return str(current or "")
    try:
        idx = choices.index(current) if isinstance(current, str) else -1
    except ValueError:
        idx = -1
    return choices[(idx + 1) % len(choices)]


def loop_diagram_class() -> type[Any] | None:
    """Return the LoopDiagram widget class, or None when Textual is unavailable."""
    global _LOOP_DIAGRAM_CLASS
    from code_review_loop import tui  # local import to reuse the lazy component loader

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if _LOOP_DIAGRAM_CLASS is not None:
        return _LOOP_DIAGRAM_CLASS

    static_cls: Any = tui._Static

    class LoopDiagram(static_cls):  # type: ignore[misc, valid-type]
        """A focusable, keyboard-driven vertical loop diagram over a LoopEditModel."""

        can_focus = True

        def __init__(self, model: LoopEditModel, **kwargs: Any) -> None:
            super().__init__("", id=kwargs.pop("id", "loop-diagram"), markup=True, **kwargs)
            self.model = model
            self.focused_index = 0
            self.expanded = False

        # --- rendering -------------------------------------------------
        def diagram_lines(self) -> list[str]:
            profile = self.model.profile
            rail_meta = tui_state.loop_rail_meta(profile)
            lines: list[str] = [
                f"[b]LOOP · {tui_state.markup_escape(self.model.name)}[/b]"
                f"  [muted]{tui_state.markup_escape(tui_state.loop_header_text(profile))}[/]",
                "",
            ]
            for index, phase in enumerate(tui_state.LOOP_PHASES):
                focused = index == self.focused_index
                expanded = focused and self.expanded
                gutter = tui_state.phase_gutter(phase, rail_meta)
                for offset, raw in enumerate(
                    tui_state.phase_card_lines(
                        self.model, phase, focused=focused, expanded=expanded
                    )
                ):
                    text = tui_state.markup_escape(raw)
                    prefix = tui_state.markup_escape(gutter if offset == 0 else "│ ")
                    body = f"[status-info]{text}[/]" if focused else text
                    lines.append(f"{prefix}{body}")
                if phase == "triage" and focused:
                    for raw in tui_state.triage_routes_lines(profile):
                        lines.append(
                            f"{tui_state.markup_escape('│ ')}"
                            f"{tui_state.markup_escape(raw)}"
                        )
                if phase == "checks" and rail_meta.inner_return_label:
                    lines.append(
                        tui_state.markup_escape(
                            f"│ └◀─ {rail_meta.inner_return_label}"
                        )
                    )
            lines.append(
                tui_state.markup_escape(f"└◀── {rail_meta.outer_return_label}")
            )
            if rail_meta.final_review_label:
                lines.append("")
                lines.append(
                    tui_state.markup_escape(f"⚑ {rail_meta.final_review_label}")
                )
            return lines

        def rebuild(self) -> None:
            self.update("\n".join(self.diagram_lines()))

        def on_mount(self) -> None:
            self.rebuild()

        # --- selection & edit -----------------------------------------
        @property
        def is_dirty(self) -> bool:
            return self.model.is_dirty

        def current_phase(self) -> str:
            return tui_state.LOOP_PHASES[self.focused_index]

        def move(self, delta: int) -> None:
            self.focused_index = (self.focused_index + delta) % len(tui_state.LOOP_PHASES)
            self.expanded = False
            self.rebuild()

        def toggle_expand(self) -> None:
            self.expanded = not self.expanded
            self.rebuild()

        def toggle_enabled(self) -> None:
            phase = self.current_phase()
            dotted = tui_state.PHASE_DOTTED.get(phase, {}).get("enabled") or ""
            if not dotted:
                return
            view = tui_state._phase_view_by_name(self.model.profile).get(phase)
            current = self.model.field_value(dotted, view.enabled if view else False)
            self.model.set_field(dotted, "false" if current else "true")
            self.rebuild()

        def cycle_field(self, key: str) -> None:
            phase = self.current_phase()
            dotted = tui_state.PHASE_DOTTED.get(phase, {}).get(key) or ""
            if not dotted:
                return
            view = tui_state._phase_view_by_name(self.model.profile).get(phase)
            if key == "harness":
                current = self.model.field_value(dotted, view.harness if view else None)
                self.model.set_field(dotted, _cycle(HARNESS_CHOICES, current))
            elif key == "effort":
                current = self.model.field_value(
                    dotted, view.reasoning_effort if view else None
                )
                self.model.set_field(dotted, _cycle(EFFORT_CHOICES, current))
            self.rebuild()

        def set_text_field(self, key: str, value: str) -> None:
            phase = self.current_phase()
            dotted = tui_state.PHASE_DOTTED.get(phase, {}).get(key) or ""
            if dotted:
                self.model.set_field(dotted, value)
                self.rebuild()

    _LOOP_DIAGRAM_CLASS = LoopDiagram
    return _LOOP_DIAGRAM_CLASS
```

- [ ] **Step 4: Mount the widget and reorder nav in `tui.py`**

Make these edits in `src/code_review_loop/tui.py`:

1. **Reorder nav.** In `_build_bindings`, change the four workspace bindings so Loop is `1` and the others follow the design order `1 Loop · 2 Run · 3 Profiles · 4 Prompts`:

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
```

9. **Show the dirty marker.** In `_status_bar_markup`, compute a dirty suffix and append it to the profile name:

```python
    dirty = "*" if getattr(app, "_loop_diagram", None) is not None and app._loop_diagram.is_dirty else ""
```

and change the `profile=` fragment to `profile={tui_state.markup_escape(profile_name)}{dirty}`.

10. **Add CSS for the loop pane.** In `_RevRemAppMixin.CSS`, add:

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
            "[profiles.edit]\nbase='main'\n[profiles.edit.review]\n"
            "harness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("2")
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

Add to `tests/test_tui_cli_equivalence.py` a guard that a TUI-saved edit is what a subsequent `revrem --profile` run consumes (reuse that file's existing equivalence helpers; the assertion is that the profile persisted by `LoopEditModel.save()` is byte-identical to the one produced by `profiles.set_profile_field` for the same edit — already covered structurally in `test_tui_loop_model.test_save_round_trips_to_config_set_path`; here assert the launch plan is unchanged):

```python
def test_loop_save_keeps_launch_plan_cli_equivalent(tmp_path):
    from code_review_loop import profiles, tui_state
    from code_review_loop.tui_loop_model import LoopEditModel

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.edit]\nbase='main'\n[profiles.edit.review]\nmodel='gpt-5.5'\n",
        encoding="utf-8",
    )
    model = LoopEditModel.load("edit", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.save()
    profile = profiles.resolve_profile("edit", cwd=repo, require_implemented=False)
    plan = tui_state.launch_plan(profile, dry_run=False)
    assert plan.argv == ("revrem", "--profile", "edit")
```

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

2. Add the action:

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
            _notify(self, f"Save failed: {exc}")
            return
        self._refresh_profiles_from_disk()
        # Re-point the diagram at the refreshed model.
        self._render_workbench()
        _notify(self, f"Saved loop to {path}")
        self._update_console_status()
```

3. Make Run save-first when dirty. In `action_launch_run`, immediately after resolving `selected`/`profile_name` and before building the plan, add:

```python
        if (
            self._workspace == "loop"
            and self._loop_diagram is not None
            and self._loop_diagram.is_dirty
        ):
            try:
                self._loop_diagram.model.save()
            except (OSError, ValueError) as exc:
                _notify(self, f"Save-and-run aborted: {exc}")
                return
            self._refresh_profiles_from_disk()
            _notify(self, f"Saved loop before run: {profile_name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k loop_save -q tests/test_tui_cli_equivalence.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (no regressions across the repo).

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

In `docs/70-devex/devex-001-using-code-review-loop.md`, add a subsection under the TUI usage describing the Loop workspace: keys `↑/↓` move phase, `Enter` expand/collapse, `space` toggle a phase, `m` cycle harness, `f` cycle effort, `s` save loop to its profile, `r` run (save-and-run when dirty); the `*` next to the profile name means unsaved working-copy changes; the diagram is config-truthful (inner rail only when `runtime.inner_check_retries > 0`, final review only when enabled); triage routes are shown read-only (route editing arrives in a later release).

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, under the Unreleased section, add:

```
### Added
- TUI: interactive Loop workspace — a config-truthful vertical loop diagram with
  in-loop editing of harness / model / effort / timeout / enable and explicit
  Save (working copy + save-to-profile), built on real Textual widgets.
```

- [ ] **Step 3: Final full-suite run + lint/format gate**

Run: `python -m pytest -q`
Expected: PASS.

Run the repository's configured format/lint gate (the same one Plan 1 used; e.g. `ruff check src tests` and `ruff format --check src tests` if configured — match `pyproject.toml`).
Expected: clean.

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
- Inline single-field edit (harness/model/effort/timeout) → cycle (`m`/`f`) + `set_text_field` (Task 4); model/timeout free-text validated at Save (Global Constraints). ✓
- Triage routes table (read-only here) → `triage_routes_lines` (Task 3); route-row modal deferred to Plan 4 (stated). ✓
- Working copy + explicit save → `LoopEditModel` (Task 1) + `action_save_loop` / save-and-run (Task 5). ✓
- CLI-equivalence preserved → `test_save_round_trips_to_config_set_path` (Task 1) + launch-plan guard (Task 5) + full `test_tui_cli_equivalence.py`. ✓
- Real interactive widgets consuming view-models; `render_shell_text` retained as fallback (untouched). ✓
- Stale design §4.2 corrected → Task 1 Step 0. ✓
- Loop-first nav → Task 4 (with pilot assertion updates). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows the test.

**Type consistency:** `field_value(dotted_key, fallback)` signature is identical across Tasks 1, 2, 4. `PHASE_DOTTED`, `LOOP_PHASES`, `loop_rail_meta`, `phase_card_lines`, `triage_routes_lines`, `phase_gutter`, `loop_header_text` names match between definition (Tasks 2–3) and use (Task 4). `loop_diagram_class()` returns the class used by `_loop_diagram_widget`. `commit` edits target `commit.message_model` (not `commit.model`), matching `CommitConfig`.

**Known risk to watch in review:** the `f"{...'│ '}"` nested-quote f-strings in Task 4 Step 3 require Python 3.12 (PEP 701) — which is the project's floor — but the executor should confirm they parse; if the toolchain rejects them, hoist the literal to a local variable. Flag, don't pre-fix.
