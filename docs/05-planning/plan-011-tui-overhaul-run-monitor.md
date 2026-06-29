---
document_id: REVREM-PLAN-011
type: PLAN
title: TUI Overhaul Plan 3 — Run / Monitor Live Mode
status: Draft
version: '0.6'
last_updated: '2026-06-28'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Plan 3 of the loop-first TUI overhaul (REVREM-DESIGN-001): reuse the
  loop diagram as a live run monitor. A pure run_loop_view derives per-phase status
  (done/running/pending/disabled), iteration and inner-retry counters from the event
  stream; LoopRunView and EventLog widgets render it live in the Run workspace.'
keywords:
- tui
- run-monitor
- live
- events
- loop-run-view
- design-001
related_ids:
- REVREM-DESIGN-001
- REVREM-PLAN-010
- REVREM-PLAN-007
---

# TUI Overhaul Plan 3 — Run / Monitor Live Mode

> **For agentic workers:** Implement this plan task-by-task using the repo's normal TDD loop: write the named failing tests first, make the smallest scoped implementation, run the listed verification, then commit only the task's files. Steps use checkbox (`- [ ]`) syntax for tracking. Do not rely on external "superpowers" skills; they are not part of this repository contract.

**Goal:** Turn the Run workspace into the live face of the loop the operator authored — the *same* vertical diagram, now showing each phase's live status (`✓` done · `▶` running · `·` pending · `⤫` disabled), the outer iteration counter and inner check-retry counter riding on the loop rails, a scrolling event tail, and the run's artifacts. This is the surface the dominant workflow (overnight pre-PR hardening) is watched on: "where is it / how many iterations left / is it converging" at a glance.

**Architecture:** Two layers under one widget set. (1) A pure, Textual-free **derivation** in a new `tui_run_state.py` — `run_loop_view(events, profile) -> RunLoopView` — folds the event stream into a per-phase status map plus iteration / inner-retry counters, translating the runner's phase vocabulary into the diagram's display phases. It imports Plan 2's `tui_loop_state` helpers for shared geometry and imports the existing `tui_state.event_views_from_events` / `event_row_text` helpers for event-tail formatting rather than moving home/history code. (2) Real **Textual widgets** in `tui_loop_widgets.py` — `LoopRunView` (the diagram in run mode) and `EventLog` (the tail) — that consume the derivation and reuse the *identical* `loop_rail_meta` / `phase_gutter` pure functions from Plan 2 so the authoring and monitoring diagrams cannot visually drift. The existing `LiveRunController` event/artifact plumbing and the app's 0.5s refresh timer drive updates.

**Tech Stack:** Python 3.12, Textual 8.2.5 (optional `[tui]` extra, lazy-imported), `pytest` + Textual pilot/`run_test`, the existing `events` model + `tui_run_controller.LiveRunController`, and the Plan 2 loop view-models (`tui_loop_state.loop_rail_meta`, `phase_gutter`, `LOOP_PHASES`).

## Plan sequence (this is Plan 3 of 4)

1. **Plan 1 (REVREM-PLAN-009):** edit primitives — **COMPLETE.**
2. **Plan 2 (REVREM-PLAN-010):** authoring Loop screen — **prerequisite** (this plan reuses `loop_rail_meta`, `phase_gutter`, `LOOP_PHASES`, and the `tui_loop_widgets` lazy-factory pattern).
3. **Plan 3 (this doc):** run / monitor live mode — `LoopRunView`, `EventLog`.
4. **Plan 4 (REVREM-PLAN-012):** profiles picker + prompts library + route-row modal editing.

> **Sequencing note:** This plan is written against Plan 2's interfaces before Plan 2 has executed. Plan 2's authoring helpers accept either a `LoopEditModel` or a plain `profiles.Profile`; live run mode passes the resolved running profile. Re-confirm `tui_loop_state.loop_rail_meta`, `phase_gutter`, and `loop_header_text` exist with those documented shapes before starting Task 3.

## Global Constraints

Every task's requirements implicitly include this section.

- **Read-only.** This plan adds no edit or write path; it only *renders* a running profile and the event/artifact stream. No `profiles` write functions are called. (This is why the root-key / coercion concerns from Plan 2 do not apply here.)
- **Config-truthful, two modes one shape.** `LoopRunView` reuses Plan 2's `loop_rail_meta(source)` and `phase_gutter(phase, rail_meta)` verbatim, passing the running resolved `profiles.Profile` as `source` — the inner rail is shown live only when `runtime.inner_check_retries > 0`, disabled phases render `⤫` and drop from the rails, and the iteration bound on the outer rail is the same `max_iterations`. The authoring and run diagrams share the rail geometry by construction.
- **Pure means no I/O and no input mutation.** `run_loop_view` may use local accumulator dictionaries while folding events; it must not mutate the supplied event list, profile, controller, or filesystem, and it must be deterministic for the same `(events, profile)` inputs.
- **Truthful to controller capability.** `LiveRunController` exposes `start` / `refresh` / `cancel` / `finish` / `read_live_events` / `stdout_lines` / `stderr_lines` — there is **no pause**. The Run footer therefore offers *stop* (`k`, the existing cancel), *logs* (`l`, toggle stdout/stderr tail), and *show artifacts* (`o`, displays the directory path) — **not** the speculative "pause" from the REVREM-DESIGN-001 §5.2 mockup. Do not invent a pause control.
- **Design reconciliation is part of this plan.** REVREM-DESIGN-001 §5.2 still shows `p pause`; Task 0 updates that design text before widget work so implementation, documentation, and review expectations agree.
- **Phase vocabulary is mapped, not assumed.** The runner emits loop phases as `review`, `triage`, `remediate`, `commit` (note: `remediate`, not `remediation`), and signals checks via `check_result` events rather than a `phase="checks"`. `run_loop_view` translates through an explicit `RUNNER_PHASE_TO_DISPLAY` map (Task 1) — never by assuming runner phase strings equal `LOOP_PHASES`.
- **Degrade gracefully.** When events are unavailable (`LiveEventSnapshot.error`) or not yet written (`.ready is False`), and when artifacts are missing, the view shows the existing waiting/unavailable states rather than failing. Missing Textual → `render_shell_text` fallback unchanged.
- **Branch & commits.** Work on `feat/tui-live-runs` (never `main`). Stage files explicitly per task — never `git add -A`. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm
  ```

## Pre-flight checks for the executor

Before Task 1, confirm the runner phase vocabulary has not changed since this plan was written (it is the one fact Task 1 rests on):

```bash
grep -rhoE 'phase="[a-z_]+"' src/code_review_loop/*.py | sort | uniq -c
```

Expected to include `review`, `triage`, `remediate`, `commit`. If a loop phase is emitted under a different string, extend `RUNNER_PHASE_TO_DISPLAY` accordingly. `preflight` / `run` / `artifacts` are run lifecycle, not loop phases, and stay unmapped (ignored).

---

## Task 0: Reconcile stale Run-monitor design controls

Before implementation, edit REVREM-DESIGN-001 §5.2 and §9:

- Replace `p pause · k stop · l logs · o open dir` with `k stop · l logs/events · o artifacts`.
- Add a short note that pause is intentionally unavailable because `LiveRunController` has cancel/stop semantics only; pausing a nested provider subprocess is future work, not this slice.
- Keep the screenshot/mockup otherwise intact so the visual target remains useful.

Run: `meminit check`
Expected: PASS, aside from unrelated pre-existing warnings.

Commit:

```bash
git add docs/30-design/design-001-loop-first-tui-overhaul.md
git commit -m "docs(tui): reconcile run monitor controls with controller capabilities"
```

## File structure

- **Modify** `docs/30-design/design-001-loop-first-tui-overhaul.md` — reconcile Run monitor controls (`k` stop, `l` logs/events, `o` artifacts; no pause).
- **Create** `src/code_review_loop/tui_run_state.py` — add `run_loop_view`, `RunLoopView`, `RunPhaseStatus`, `RUNNER_PHASE_TO_DISPLAY`, `RUN_STATE_GLYPHS`, and an event-tail formatter `event_tail_lines`.
- **Modify** `src/code_review_loop/tui_loop_widgets.py` — add lazy `loop_run_view_class()` (`LoopRunView`) and `event_log_class()` (`EventLog`).
- **Modify** `src/code_review_loop/tui.py` — mount `LoopRunView` + `EventLog` into the Run workspace; wire the existing 0.5s refresh + launch auto-switch to them; Run footer controls (`k`/`l`/`o`).
- **Create** `tests/test_tui_run_view.py` — pure-derivation unit tests (synthetic event lists).
- **Create** `tests/test_tui_run_snapshots.py` — SVG/rendered-output snapshots for representative live monitor states.
- **Modify** `tests/test_tui_pilot_smoke.py` — live-run pilot assertions on the new widgets.
- **Modify** `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`.

---

## Task 1: Pure run-state derivation (`run_loop_view`)

Fold an event list into per-phase status + counters. This is the testable heart of the live view; everything visual reads from it.

**Files:**
- Create: `src/code_review_loop/tui_run_state.py`
- Test: `tests/test_tui_run_view.py`

**Interfaces:**
- Consumes: `events.Event` (`.kind`, `.phase`, `.iteration`, `.payload`, `.seq`); `profiles.Profile`; the Plan 2 `LOOP_PHASES`; existing `event_detail`.
- Produces:
  - `RUNNER_PHASE_TO_DISPLAY: dict[str, str] = {"review":"review","triage":"triage","remediate":"remediation","commit":"commit"}`
  - `RUN_STATE_GLYPHS: dict[str, str]` for `done`/`running`/`pending`/`disabled`.
  - `@dataclass(frozen=True) class RunPhaseStatus`: `name: str`, `state: str`, `detail: str`.
  - `@dataclass(frozen=True) class RunLoopView`: `phases: tuple[RunPhaseStatus, ...]`, `iteration: int | None`, `max_iterations: int`, `inner_retry: int`, `inner_check_retries: int`.
  - `run_loop_view(events, profile) -> RunLoopView`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_run_view.py`:

```python
from __future__ import annotations

from pathlib import Path

from code_review_loop import events as event_model
from code_review_loop import profiles, tui_run_state


def _profile(tmp_path: Path, *, triage=False, commit=True, inner=0) -> profiles.Profile:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    body = [
        "[profiles.p]",
        "[profiles.p.pipeline]",
        "base='main'",
        "max_iterations=11",
        "checks=['pytest -q']",
        "[profiles.p.triage]",
        f"enabled={'true' if triage else 'false'}",
        "[profiles.p.commit]",
        f"enabled={'true' if commit else 'false'}",
        "[profiles.p.runtime]",
        f"inner_check_retries={inner}",
    ]
    (repo / ".revrem.toml").write_text("\n".join(body) + "\n", encoding="utf-8")
    return profiles.resolve_profile("p", cwd=repo, require_implemented=False)


def _ev(seq, kind, phase=None, iteration=None, **payload):
    return event_model.Event(
        run_id="r", seq=seq, kind=kind, phase=phase, iteration=iteration, payload=payload
    )


def test_pending_when_no_events(tmp_path):
    view = tui_run_state.run_loop_view((), _profile(tmp_path))
    states = {p.name: p.state for p in view.phases}
    assert states["review"] == "pending"
    assert view.iteration is None
    assert view.max_iterations == 11


def test_running_and_done_states_map_remediate(tmp_path):
    evs = (
        _ev(1, "phase_start", "review", 1),
        _ev(2, "phase_result", "review", 1, detail="2 findings"),
        _ev(3, "phase_start", "remediate", 1),  # runner says "remediate"
    )
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path))
    states = {p.name: p.state for p in view.phases}
    assert states["review"] == "done"
    assert states["remediation"] == "running"  # mapped to display name
    assert states["commit"] == "pending"
    assert view.iteration == 1


def test_disabled_phases_render_disabled(tmp_path):
    view = tui_run_state.run_loop_view((), _profile(tmp_path, triage=False, commit=False))
    states = {p.name: p.state for p in view.phases}
    assert states["triage"] == "disabled"
    assert states["commit"] == "disabled"


def test_checks_state_from_check_result_events(tmp_path):
    evs = (
        _ev(1, "phase_start", "remediate", 2),
        _ev(2, "phase_result", "remediate", 2),
        _ev(3, "check_result", "test", 2, name="pytest -q", passed=True),
    )
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path))
    states = {p.name: p.state for p in view.phases}
    assert states["checks"] == "done"


def test_inner_retry_counts_repeated_remediate_in_iteration(tmp_path):
    evs = (
        _ev(1, "phase_start", "remediate", 3),
        _ev(2, "phase_result", "remediate", 3),
        _ev(3, "check_result", "test", 3, passed=False),
        _ev(4, "phase_start", "remediate", 3),  # second remediate => inner retry 1
        _ev(5, "phase_result", "remediate", 3),
    )
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path, inner=2))
    assert view.inner_check_retries == 2
    assert view.inner_retry == 1


def test_inner_retry_counts_sub_iteration_labels_as_same_outer_iteration(tmp_path):
    evs = (
        _ev(1, "phase_start", "remediate", 1),
        _ev(2, "check_result", "test", "1.1", passed=False),
        _ev(3, "phase_start", "remediate", "1.2"),
    )
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path, inner=2))
    assert view.iteration == 1
    assert view.inner_retry == 1


def test_new_outer_iteration_resets_prior_phase_states(tmp_path):
    evs = (
        _ev(1, "phase_start", "review", 1),
        _ev(2, "phase_result", "review", 1, status="findings"),
        _ev(3, "phase_start", "triage", 1),
        _ev(4, "phase_result", "triage", 1),
        _ev(5, "phase_start", "remediate", 1),
        _ev(6, "phase_result", "remediate", 1),
        _ev(7, "check_result", "test", 1, passed=True),
        _ev(8, "phase_start", "review", 2),
    )
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path, triage=True, inner=1))
    states = {p.name: p.state for p in view.phases}
    assert states["review"] == "running"
    assert states["triage"] == "pending"
    assert states["remediation"] == "pending"
    assert states["checks"] == "pending"


def test_orphan_check_result_marks_checks_without_remediate_start(tmp_path):
    evs = (_ev(1, "check_result", "check", "1.1", passed=False),)
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path))
    states = {p.name: p.state for p in view.phases}
    details = {p.name: p.detail for p in view.phases}
    assert states["checks"] == "done"
    assert details["checks"] == "failed"
    assert view.iteration == 1


def test_string_outer_iteration_change_resets_prior_states(tmp_path):
    evs = (
        _ev(1, "phase_start", "review", "1"),
        _ev(2, "phase_result", "review", "1"),
        _ev(3, "check_result", "check", "1.1", passed=True),
        _ev(4, "phase_start", "review", "2"),
    )
    view = tui_run_state.run_loop_view(evs, _profile(tmp_path))
    states = {p.name: p.state for p in view.phases}
    assert view.iteration == 2
    assert states["review"] == "running"
    assert states["checks"] == "pending"
```

Before implementing the counter, inspect a real artifact or fixture with `runtime.inner_check_retries > 0` and confirm the event shape. The runner emits integer outer iterations for normal phase starts, but check-attempt labels may be strings such as `"1.1"`. The counter must normalize both `1` and `"1.2"` to outer iteration `1` before deciding whether to reset `current_iter_remediate_starts`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_run_view.py -q`
Expected: FAIL — `ModuleNotFoundError` or `AttributeError` for `code_review_loop.tui_run_state.run_loop_view`.

- [ ] **Step 3: Write the implementation**

Create `src/code_review_loop/tui_run_state.py`. Import `dataclass`, `Any`, `profiles`, `tui_loop_state`, and `tui_state.event_detail`. The implementation below keeps local accumulator mutation private to the function and does not mutate inputs.

```python
RUNNER_PHASE_TO_DISPLAY: dict[str, str] = {
    "review": "review",
    "triage": "triage",
    "remediate": "remediation",
    "commit": "commit",
}
RUN_STATE_GLYPHS: dict[str, str] = {
    "done": "✓",
    "running": "▶",
    "pending": "·",
    "disabled": "⤫",
}


@dataclass(frozen=True)
class RunPhaseStatus:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class RunLoopView:
    phases: tuple[RunPhaseStatus, ...]
    iteration: int | None
    max_iterations: int
    inner_retry: int
    inner_check_retries: int


def _phase_enabled_map(profile: profiles.Profile) -> dict[str, bool]:
    return {phase.name: phase.enabled for phase in tui_state.pipeline_phases(profile)}


def _outer_iteration(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        head = value.split(".", 1)[0]
        if head.isdecimal():
            return int(head)
    return None


def run_loop_view(
    events: "tuple[Any, ...] | list[Any]", profile: profiles.Profile
) -> RunLoopView:
    enabled = _phase_enabled_map(profile)
    states: dict[str, str] = {name: "pending" for name in tui_loop_state.LOOP_PHASES}
    details: dict[str, str] = {name: "" for name in tui_loop_state.LOOP_PHASES}
    for name, is_on in enabled.items():
        if not is_on:
            states[name] = "disabled"

    iteration: int | None = None
    current_outer_iteration: int | None = None
    current_iter_remediate_starts = 0
    last_iteration_for_remediate: int | None = None
    any_check_result = False
    last_check_passed: bool | None = None

    for event in events:
        event_outer_iteration = _outer_iteration(event.iteration)
        if event_outer_iteration is not None:
            if current_outer_iteration is not None and event_outer_iteration != current_outer_iteration:
                for name, is_on in enabled.items():
                    if is_on:
                        states[name] = "pending"
                        details[name] = ""
                current_iter_remediate_starts = 0
                last_iteration_for_remediate = None
                any_check_result = False
                last_check_passed = None
            current_outer_iteration = event_outer_iteration
            iteration = event_outer_iteration

        display = RUNNER_PHASE_TO_DISPLAY.get(event.phase or "")
        if display is not None and states.get(display) != "disabled":
            if event.kind == "phase_start":
                states[display] = "running"
                if display == "remediation":
                    if last_iteration_for_remediate != event_outer_iteration:
                        current_iter_remediate_starts = 0
                        last_iteration_for_remediate = event_outer_iteration
                    current_iter_remediate_starts += 1
            elif event.kind == "phase_result":
                states[display] = "done"
                detail = event_detail(event)
                if detail:
                    details[display] = detail

        if event.kind == "check_result":
            any_check_result = True
            passed = event.payload.get("passed")
            if isinstance(passed, bool):
                last_check_passed = passed

    if states.get("checks") != "disabled" and any_check_result:
        states["checks"] = "done"
        if last_check_passed is False:
            details["checks"] = "failed"
        elif last_check_passed is True:
            details["checks"] = "passed"

    inner_retry = max(0, current_iter_remediate_starts - 1)
    return RunLoopView(
        phases=tuple(
            RunPhaseStatus(name=name, state=states[name], detail=details[name])
            for name in tui_loop_state.LOOP_PHASES
        ),
        iteration=iteration,
        max_iterations=profile.pipeline.max_iterations,
        inner_retry=inner_retry,
        inner_check_retries=profile.runtime.inner_check_retries,
    )
```

`tui_state.event_detail(event)` delegates to `events.compact_detail(event)` and is used only for `phase_result` rows here. Checks are signalled through `check_result` events, so their display state/detail stays in the explicit `check_result` branch above rather than relying on a synthetic `phase="checks"` phase result.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_run_view.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_run_state.py tests/test_tui_run_view.py
git commit -m "feat(tui): derive live run-loop status from the event stream"
```

---

## Task 2: Event-tail formatter

A compact, bounded tail of the event stream for the live `EventLog`, reusing the existing `RunEventView` / `event_row_text` plumbing.

**Files:**
- Modify: `src/code_review_loop/tui_run_state.py`
- Test: `tests/test_tui_run_view.py` (add cases)

**Interfaces:**
- Consumes: `events.Event`; existing `tui_state.event_views_from_events`, `tui_state.event_row_text`.
- Produces: `event_tail_lines(events, *, limit=8) -> tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_run_view.py`:

```python
def test_event_tail_lines_bounded_and_formatted():
    evs = [_ev(i, "phase_output", "review", 1, text=f"line {i}") for i in range(1, 20)]
    lines = tui_run_state.event_tail_lines(evs, limit=5)
    assert len(lines) == 5
    assert "review" in lines[-1]


def test_event_tail_lines_empty():
    assert tui_run_state.event_tail_lines(()) == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_run_view.py -k event_tail -q`
Expected: FAIL — `AttributeError: ... 'event_tail_lines'`.

- [ ] **Step 3: Write the implementation**

Append to `src/code_review_loop/tui_run_state.py`:

```python
def event_tail_lines(
    events: "tuple[Any, ...] | list[Any]", *, limit: int = 8
) -> tuple[str, ...]:
    if not events:
        return ()
    views = tui_state.event_views_from_events(tuple(events)[-limit:])
    return tuple(tui_state.event_row_text(view) for view in views)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_run_view.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_run_state.py tests/test_tui_run_view.py
git commit -m "feat(tui): add bounded event-tail formatter"
```

---

## Task 3: `LoopRunView` widget (the diagram in run mode)

The live diagram. Reuses Plan 2's `loop_rail_meta` + `phase_gutter` so the run view and the authoring view share rail geometry, swapping per-phase content for status glyphs + counters. Live mode passes a resolved `profiles.Profile`; authoring mode passes a `LoopEditModel`.

**Files:**
- Modify: `src/code_review_loop/tui_loop_widgets.py`
- Test: `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `tui_run_state.run_loop_view`, `tui_run_state.RUN_STATE_GLYPHS`, `tui_loop_state.loop_rail_meta`, `phase_gutter`, `LOOP_PHASES`, `loop_header_text` (Tasks 1 + Plan 2); a `LiveRunController` and a `profiles.Profile` (the running profile).
- Produces: `loop_run_view_class() -> type | None` (lazy factory, same pattern as Plan 2's `loop_diagram_class`); `LoopRunView` widget with `set_state(controller, profile)` and `rebuild()`.

- [ ] **Step 1: Write the failing pilot test**

Append to `tests/test_tui_pilot_smoke.py`:

```python
def test_run_workspace_shows_live_loop_diagram(tmp_path, monkeypatch):
    from support.git_fixtures import init_repo

    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="slow_cancel", artifact_dir="runs/live-mon")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("r")
            await pilot.press("r")  # confirm launch -> auto-switches to Run workspace
            await _wait_for(
                lambda: app.query("#loop-run").first() is not None,
                pilot_pause=pilot.pause,
            )
            rendered = _render(app, "#loop-run")
            assert "review" in rendered  # the diagram, not a text dump
            app.live_run_controller.cancel(grace_seconds=1)

    asyncio.run(run())
```

(Reuses the file's existing `_write_live_profile`, `_wait_for`, `_render` helpers. The test first asserts the real widget exists, then asserts its content.)

Append direct widget-state tests to `tests/test_tui_pilot_smoke.py` so the graceful-degradation contract is not left to live subprocess timing:

```python
class _FakeLiveController:
    status = "running"

    def __init__(self, snapshot: tui_run_controller.LiveEventSnapshot) -> None:
        self._snapshot = snapshot

    def read_live_events(self) -> tui_run_controller.LiveEventSnapshot:
        return self._snapshot


def _single_widget_app(widget):
    components = tui._load_textual_components()
    if components is None:
        pytest.skip("Textual is not installed")

    class SingleWidgetApp(components.app.App):  # type: ignore[misc, valid-type]
        def compose(self):
            yield widget

    return SingleWidgetApp()


def _loop_run_profile(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n",
        encoding="utf-8",
    )
    return profiles.resolve_profile("p", cwd=repo, require_implemented=False)


def test_loop_run_view_waits_when_events_not_ready(tmp_path):
    async def run() -> None:
        cls = tui_loop_widgets.loop_run_view_class()
        if cls is None:
            pytest.skip("Textual is not installed")
        profile = _loop_run_profile(tmp_path)
        async with _single_widget_app(cls()).run_test() as pilot:
            widget = pilot.app.query_one("#loop-run")
            widget.set_state(
                _FakeLiveController(tui_run_controller.LiveEventSnapshot(ready=False)),
                profile,
            )
            widget.rebuild()
            await pilot.pause()
            assert "events: waiting for events.jsonl" in str(widget.render())

    asyncio.run(run())


def test_loop_run_view_reports_event_read_errors(tmp_path):
    async def run() -> None:
        cls = tui_loop_widgets.loop_run_view_class()
        if cls is None:
            pytest.skip("Textual is not installed")
        profile = _loop_run_profile(tmp_path)
        async with _single_widget_app(cls()).run_test() as pilot:
            widget = pilot.app.query_one("#loop-run")
            widget.set_state(
                _FakeLiveController(
                    tui_run_controller.LiveEventSnapshot(error="bad json", ready=True)
                ),
                profile,
            )
            widget.rebuild()
            await pilot.pause()
            rendered = str(widget.render())
            assert "events: unavailable" in rendered
            assert "bad json" in rendered

    asyncio.run(run())


def test_event_log_waits_when_events_not_ready():
    async def run() -> None:
        cls = tui_loop_widgets.event_log_class()
        if cls is None:
            pytest.skip("Textual is not installed")
        async with _single_widget_app(cls()).run_test() as pilot:
            widget = pilot.app.query_one("#event-log")
            widget.set_controller(
                _FakeLiveController(tui_run_controller.LiveEventSnapshot(ready=False))
            )
            widget.rebuild()
            await pilot.pause()
            assert "waiting for events.jsonl" in str(widget.render())

    asyncio.run(run())
```

Use the concrete app/helpers already present in `test_tui_pilot_smoke.py` where names differ; these tests must query real widgets and assert rendered content.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k run_workspace_shows_live -q`
Expected: FAIL — `#loop-run` widget not found.

- [ ] **Step 3: Write the widget**

Append to `src/code_review_loop/tui_loop_widgets.py` (mirror `loop_diagram_class`'s lazy-factory structure):

```python
_LOOP_RUN_VIEW_CLASS: type[Any] | None = None


def loop_run_view_class() -> type[Any] | None:
    global _LOOP_RUN_VIEW_CLASS
    from code_review_loop import tui
    from code_review_loop import tui_loop_state, tui_run_state

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if _LOOP_RUN_VIEW_CLASS is not None:
        return _LOOP_RUN_VIEW_CLASS

    static_cls: Any = tui._Static

    class LoopRunView(static_cls):  # type: ignore[misc, valid-type]
        """The loop diagram in live run mode (status glyphs + counters)."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__("", id=kwargs.pop("id", "loop-run"), markup=True, **kwargs)
            self.controller = None
            self.profile = None

        def set_state(self, controller: Any, profile: Any) -> None:
            self.controller = controller
            self.profile = profile

        def run_lines(self) -> list[str]:
            if self.profile is None or self.controller is None:
                return ["[muted]No active run.[/]"]
            snapshot = self.controller.read_live_events()
            if snapshot.error:
                return [
                    f"[muted]events: unavailable ({tui_state.markup_escape(snapshot.error)})[/]"
                ]
            if not snapshot.ready:
                return ["[muted]events: waiting for events.jsonl[/]"]
            view = tui_run_state.run_loop_view(snapshot.events, self.profile)
            rail_meta = tui_loop_state.loop_rail_meta(self.profile)
            iter_text = (
                f"iteration {view.iteration} / {view.max_iterations}"
                if view.iteration is not None
                else f"max {view.max_iterations}"
            )
            lines: list[str] = [
                f"[b]RUN · {tui_state.markup_escape(self.profile.name)}[/b]",
                f"[muted]{tui_state.markup_escape(self.controller.status)} · "
                f"{tui_state.markup_escape(iter_text)}[/]",
                "",
            ]
            status_by_name = {p.name: p for p in view.phases}
            for phase in tui_loop_state.LOOP_PHASES:
                status = status_by_name[phase]
                glyph = tui_run_state.RUN_STATE_GLYPHS.get(status.state, "·")
                gutter = tui_state.markup_escape(tui_loop_state.phase_gutter(phase, rail_meta))
                detail = f"  {status.detail}" if status.detail else ""
                lines.append(
                    f"{gutter}{glyph} {tui_state.markup_escape(phase)}"
                    f"{tui_state.markup_escape(detail)}"
                )
                if phase == "checks" and rail_meta.inner_rail:
                    lines.append(
                        tui_state.markup_escape(
                            f"│ └◀─ inner retry {view.inner_retry} / {view.inner_check_retries}"
                        )
                    )
            lines.append(
                tui_state.markup_escape(f"└◀── {rail_meta.outer_return_label}")
            )
            return lines

        def rebuild(self) -> None:
            self.update("\n".join(self.run_lines()))

    _LOOP_RUN_VIEW_CLASS = LoopRunView
    return _LOOP_RUN_VIEW_CLASS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k run_workspace_shows_live -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui_loop_widgets.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): LoopRunView renders the loop diagram live"
```

---

## Task 3b: LoopRunView SVG snapshot coverage

Lock the live-monitor rendered output promised by REVREM-DESIGN-001 §8. These snapshots should use synthetic event streams so they are deterministic and do not depend on provider subprocess timing.

**Files:**
- Create: `tests/test_tui_run_snapshots.py`

**Requirements:**
- Add `pytest-textual-snapshot` to the `dev` optional dependency group in `pyproject.toml` if Plan 010 did not already add it; do **not** add it to the runtime `[tui]` extra. Use the repo's Textual snapshot mechanism if available (`pytest-textual-snapshot` / SVG export). If the dependency is still absent, add a guarded skip and TODO rather than replacing the coverage with string-only assertions.
- Capture at least these `LoopRunView` states:
  - no events yet / pending;
  - review running;
  - remediation running after review findings;
  - check failure with inner retry visible;
  - disabled triage;
  - completed clear;
  - completed with findings.
- Use a stable terminal size (`120x40` minimum) and deterministic timestamps/details in the synthetic events.

Run: `python -m pytest tests/test_tui_run_snapshots.py -q`
Expected: PASS with committed snapshots or SKIP only when the snapshot dependency is not installed.

- [ ] **Commit**

```bash
git add tests/test_tui_run_snapshots.py tests/snapshots
git commit -m "test(tui): snapshot live run monitor states"
```

---

## Task 4: `EventLog` widget + Run-workspace mount + controls

Mount `LoopRunView` and a scrolling `EventLog` into the Run workspace, wire the existing 0.5s refresh + launch auto-switch to them, and add the truthful Run footer controls.

**Files:**
- Modify: `src/code_review_loop/tui_loop_widgets.py`, `src/code_review_loop/tui.py`
- Test: `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: `loop_run_view_class`, `event_log_class`, `event_tail_lines`, the existing `LiveRunController`, and `tui`'s refresh hooks (`_refresh_live_run`, `set_interval`, `action_launch_run`).
- Produces: `event_log_class() -> type | None`; `EventLog` widget with `set_controller(controller)` and `rebuild()`; Run-workspace mounting + `o` show-artifacts / `l` logs-toggle actions.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_pilot_smoke.py`:

```python
def test_run_workspace_event_log_and_artifacts(tmp_path, monkeypatch):
    from support.git_fixtures import init_repo

    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="slow_cancel", artifact_dir="runs/live-log")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("r")
            await pilot.press("r")
            await _wait_for(
                lambda: app.live_run_controller.launch is not None,
                pilot_pause=pilot.pause,
            )
            event_log = app.query_one("#event-log")
            assert event_log is not None
            # artifacts dir is surfaced in the run footer
            assert "artifacts" in _render(app, "#footer-bar").lower() or (
                "live-log" in _render(app, "#loop-run")
            )
            app.live_run_controller.cancel(grace_seconds=1)

    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k event_log_and_artifacts -q`
Expected: FAIL — `#event-log` not found.

- [ ] **Step 3: Add the `EventLog` widget**

Append to `src/code_review_loop/tui_loop_widgets.py` (same lazy-factory pattern):

```python
_EVENT_LOG_CLASS: type[Any] | None = None


def event_log_class() -> type[Any] | None:
    global _EVENT_LOG_CLASS
    from code_review_loop import tui
    from code_review_loop import tui_run_state

    components = tui._load_textual_components()
    if components is None:
        return None
    tui._install_textual_components(components)
    if _EVENT_LOG_CLASS is not None:
        return _EVENT_LOG_CLASS

    static_cls: Any = tui._Static

    class EventLog(static_cls):  # type: ignore[misc, valid-type]
        """Scrolling tail of the live event stream."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__("", id=kwargs.pop("id", "event-log"), markup=True, **kwargs)
            self.controller = None
            self.show_logs = False

        def set_controller(self, controller: Any) -> None:
            self.controller = controller

        def rebuild(self) -> None:
            if self.controller is None:
                self.update("[muted]events: waiting for a run[/]")
                return
            if self.show_logs:
                body = self.controller.stdout_lines()[-12:]
                head = "[b]stdout[/b]"
            else:
                snapshot = self.controller.read_live_events()
                if snapshot.error:
                    self.update(
                        f"events: unavailable ({tui_state.markup_escape(snapshot.error)})"
                    )
                    return
                if not snapshot.ready:
                    self.update("[muted]events: waiting for events.jsonl[/]")
                    return
                body = tui_run_state.event_tail_lines(snapshot.events, limit=8)
                head = "[b]events[/b]"
            rows = "\n".join(tui_state.markup_escape(line) for line in body) or "[muted]…[/]"
            self.update(f"{head}\n{rows}")

    _EVENT_LOG_CLASS = EventLog
    return _EVENT_LOG_CLASS
```

- [ ] **Step 4: Mount into the Run workspace in `tui.py`**

1. **Compose the run widgets.** In `compose`, inside the `with _Horizontal(id="body"):` block (after the loop-pane added by Plan 2), add a run pane:

```python
                run_view_cls = _loop_run_widget(self)
                event_log_cls = _event_log_widget(self)
                if run_view_cls is not None and event_log_cls is not None and _Vertical is not None:
                    with _Vertical(id="run-pane"):
                        yield run_view_cls
                        yield event_log_cls
```

2. **Add the widget helpers** near `_loop_diagram_widget` (Plan 2):

```python
def _loop_run_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    cls = tui_loop_widgets.loop_run_view_class()
    if cls is None:
        return None
    widget = cls()
    app._loop_run_view = widget
    return widget


def _event_log_widget(app: Any) -> Any | None:
    from code_review_loop import tui_loop_widgets

    cls = tui_loop_widgets.event_log_class()
    if cls is None:
        return None
    widget = cls()
    app._event_log = widget
    return widget
```

In `__init__`, initialise `self._loop_run_view = None` and `self._event_log = None`.

3. **Toggle the run pane by workspace.** In `_render_workbench`, extend the Plan 2 display toggles so `#run-pane` shows only on the Run workspace and the legacy text panes hide on both loop and run:

```python
        on_loop = self._workspace == "loop"
        on_run = self._workspace == "run"
        _set_widget_display(self, "#loop-pane", on_loop)
        _set_widget_display(self, "#run-pane", on_run)
        _set_widget_display(self, "#left-pane", not (on_loop or on_run))
        _set_widget_display(self, "#right-pane", not (on_loop or on_run))
```

4. **Feed the run widgets the controller + profile.** In `_render_live_monitor` and at the end of `_refresh_live_run`, push state into the widgets:

```python
        if self._loop_run_view is not None:
            profile = self._profile_by_name(self._profile_name())
            self._loop_run_view.set_state(self.live_run_controller, profile)
            self._loop_run_view.rebuild()
        if self._event_log is not None:
            self._event_log.set_controller(self.live_run_controller)
            self._event_log.rebuild()
```

5. **Run footer controls.** Add bindings in `_build_bindings`:

```python
        ("l", "toggle_logs", "Logs"),
        ("o", "show_artifacts", "Show artifacts"),
```

and the actions on `_RevRemAppMixin`:

```python
    def action_toggle_logs(self) -> None:
        if self._workspace == "run" and self._event_log is not None:
            self._event_log.show_logs = not self._event_log.show_logs
            self._event_log.rebuild()

    def action_show_artifacts(self) -> None:
        if self.live_run_controller.launch is None:
            _notify(self, "No run artifacts yet.")
            return
        _notify(self, f"Artifacts: {self.live_run_controller.launch.artifact_dir}")
```

(`action_cancel_run` / `k` already exists and serves *stop*; do not add a pause.)

6. **Add CSS** for `#run-pane` in `_RevRemAppMixin.CSS`:

```css
    #run-pane { width: 1fr; height: 1fr; padding: 0 1; overflow-y: auto; }
    #loop-run { height: auto; }
    #event-log { height: auto; margin-top: 1; }
```

- [ ] **Step 5: Run the new pilot tests + full TUI suite**

Run: `python -m pytest tests/test_tui_pilot_smoke.py tests/test_tui.py tests/test_tui_run_controller.py -q`
Expected: PASS (existing + new).

- [ ] **Step 6: Commit**

```bash
git add src/code_review_loop/tui_loop_widgets.py src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): mount live run monitor (LoopRunView + EventLog)"
```

---

## Task 5: Launch auto-switch + steady-state refresh integration

Make a launched run land on the Run workspace with the live diagram already populated, and ensure the steady-state 0.5s refresh updates both widgets without flicker or stale profile.

**Files:**
- Modify: `src/code_review_loop/tui.py`
- Test: `tests/test_tui_pilot_smoke.py`

**Interfaces:**
- Consumes: existing `action_launch_run` (sets `_workspace="run"`), `_refresh_live_run`, `TERMINAL_STATUSES`.
- Produces: a verified live-update path; no new public API.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tui_pilot_smoke.py`:

```python
def test_live_run_reaches_running_glyph_in_diagram(tmp_path, monkeypatch):
    from support.git_fixtures import init_repo

    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="slow_cancel", artifact_dir="runs/live-glyph")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("r")
            await pilot.press("r")
            assert app._workspace == "run"  # auto-switched
            await _wait_for(
                lambda: app.live_run_controller.status in {"running", "starting"}
                and app._loop_run_view is not None,
                pilot_pause=pilot.pause,
            )
            app._refresh_live_run()
            await pilot.pause()
            rendered = _render(app, "#loop-run")
            # the diagram reflects live status (a glyph from RUN_STATE_GLYPHS is present)
            assert any(g in rendered for g in ("▶", "✓", "·"))
            app.live_run_controller.cancel(grace_seconds=1)

    asyncio.run(run())


def test_saved_loop_edit_launches_run_with_matching_live_diagram(tmp_path, monkeypatch):
    """Cross-plan guard: Plan 2 working-copy save feeds Plan 3 live rendering."""
    from support.git_fixtures import init_repo

    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="slow_cancel", artifact_dir="runs/edited-live")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("1")  # Loop
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "slow_cancel")
            diagram.set_loop_meta_field("max_iterations", "3")
            app.action_save_loop()
            await pilot.pause()
            await pilot.press("r")
            await pilot.press("r")
            await _wait_for(
                lambda: app._workspace == "run" and app._loop_run_view is not None,
                pilot_pause=pilot.pause,
            )
            rendered = _render(app, "#loop-run")
            assert "live" in rendered
            assert "3" in rendered  # max-iteration rail/header from the saved profile
            app.live_run_controller.cancel(grace_seconds=1)

    asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails (or reveals a wiring gap)**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -k "reaches_running_glyph or saved_loop_edit_launches" -q`
Expected: FAIL if `_refresh_live_run` does not yet refresh the run widgets, or `_workspace` is not `run`.

- [ ] **Step 3: Implement the integration**

In `src/code_review_loop/tui.py`:

1. Ensure `action_launch_run` already sets `self._workspace = "run"` and `self._focused_pane = "right"` (it does in the Plan 2 base) — after it, call `self._render_workbench()` so the run pane becomes visible immediately, then `self._render_live_monitor()` to populate it.

2. In `_refresh_live_run`, after `self.live_run_controller.refresh()`, call `self._render_live_monitor()` (which now also rebuilds the run widgets per Task 4 Step 4). Guard against rebuilding when not on the Run workspace to avoid needless work:

```python
    def _refresh_live_run(self) -> None:
        if self._cancel_in_progress:
            return
        if self.live_run_controller.status == "idle":
            return
        if self.live_run_controller.status in tui_run_controller.TERMINAL_STATUSES:
            self._render_live_monitor()  # final paint, then stop refreshing
            return
        self.live_run_controller.refresh()
        self._render_live_monitor()
```

- [ ] **Step 4: Run the test + full suite**

Run: `python -m pytest tests/test_tui_pilot_smoke.py -q && ./scripts/dev-check`
Expected: PASS (no regressions repo-wide).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/tui.py tests/test_tui_pilot_smoke.py
git commit -m "feat(tui): auto-switch to live run monitor and refresh it in place"
```

---

## Task 6: Documentation + changelog + final verification

**Files:**
- Modify: `docs/70-devex/devex-001-using-code-review-loop.md`, `CHANGELOG.md`

- [ ] **Step 1: Document the Run workspace**

In `docs/70-devex/devex-001-using-code-review-loop.md`, update the replacement TUI section introduced by Plan 010; do not add a conflicting subsection. Describe the live Run monitor: the same loop diagram, now showing `✓` done · `▶` running · `·` pending · `⤫` disabled; the outer `iteration n / max` and inner `inner retry n / N` counters on the rails; the event tail; controls `k` stop · `l` toggle logs/events · `o` show artifacts dir. State plainly that **pause is not available** (the runner is stopped, not paused).

- [ ] **Step 2: CHANGELOG entry**

Under Unreleased → Added:

```
- TUI: live Run monitor — the loop diagram rendered live with per-phase status,
  iteration and inner check-retry counters, a scrolling event tail, and artifacts;
  reuses the authoring diagram's rail geometry so the two views cannot drift.
```

- [ ] **Step 3: Final full-suite + lint/format gate**

Run: `./scripts/dev-check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/70-devex/devex-001-using-code-review-loop.md CHANGELOG.md
git commit -m "docs(tui): document the live run monitor"
```

---

## Self-review (run by the plan author before execution)

**Spec coverage (REVREM-DESIGN-001 §5.2, §6):**
- Same diagram, live, two modes → `LoopRunView` reuses `loop_rail_meta` + `phase_gutter` (Task 3). ✓
- Status glyphs `✓/▶/·/⤫` → `RUN_STATE_GLYPHS` + `run_loop_view` states (Task 1). ✓
- Iteration + inner-retry counters on the rails → `RunLoopView.iteration`/`inner_retry` rendered on the rails (Tasks 1, 3). ✓
- Event tail → `event_tail_lines` + `EventLog` (Tasks 2, 4). ✓
- Artifacts + controls → footer `k`/`l`/`o` (Task 4); **pause dropped** with stated reason (Global Constraints). ✓
- Backed by existing `run_monitor_view`/event plumbing + `LiveRunController` → `read_live_events` consumed directly (Tasks 3–5). ✓
- Degrades gracefully on missing events/artifacts/Textual → guarded in `EventLog`/`LoopRunView`; `render_shell_text` untouched. ✓

**Phase-vocabulary correctness:** `RUNNER_PHASE_TO_DISPLAY` maps the *actual* runner strings (`remediate` → `remediation`), verified by grep on 2026-06-28; checks derived from `check_result` events, not a non-existent `phase="checks"`. A pre-flight grep step re-verifies before Task 1.

**Placeholder scan:** none — every code/test step shows complete content.

**Type consistency:** `tui_run_state.run_loop_view(events, profile)`, `RunLoopView`, `RunPhaseStatus`, `RUN_STATE_GLYPHS`, `event_tail_lines`, `loop_run_view_class`, `event_log_class`, `tui_loop_state.phase_gutter`, `loop_rail_meta`, and `LOOP_PHASES` names match between definition and use across tasks. `LoopRunView.set_state(controller, profile)` and `EventLog.set_controller(controller)` signatures match their `tui.py` call sites.

**Dependency on Plan 2:** reuses `tui_loop_state.loop_rail_meta`, `phase_gutter`, `LOOP_PHASES`, `loop_header_text`, the `#body`/display-toggle layout, and the `tui_loop_widgets` lazy-factory pattern — all introduced in Plan 2. `loop_rail_meta` / `loop_header_text` accept both `LoopEditModel` and `profiles.Profile`; this plan uses the profile path. Flagged in the sequencing note; re-confirm before Task 3.
