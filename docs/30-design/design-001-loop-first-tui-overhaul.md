---
document_id: REVREM-DESIGN-001
type: Design
title: Loop-First TUI Overhaul
status: Draft
version: "0.4"
last_updated: '2026-07-11'
owner: GitCmurf
area: product
docops_version: "2.0"
template_type: design-standard
template_version: "2.0"
description: "A loop-first redesign of the revrem TUI: the loop pipeline becomes an editable vertical diagram that is the spine of both authoring and live monitoring; profiles demote to a save/load layer; prompts gain a curation library."
keywords:
  - revrem
  - tui
  - textual
  - loop
  - profiles
  - prompts
  - ux
related_ids:
  - REVREM-PRD-001
  - REVREM-PLAN-007
  - REVREM-ADR-002
---

> **Document ID:** REVREM-DESIGN-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.4
> **Last Updated:** 2026-07-11
> **Type:** Design

# Design: Loop-First TUI Overhaul

## 1. Problem

The current TUI (see `RevRemApp` in `src/code_review_loop/tui.py`) renders every screen
as plain text lines (`tuple[str]`) piped into `Static` widgets, laid out as a left
list / right dense-detail two-pane "workbench". This reads as a text dump and has two
named problems:

1. **Profiles are hard to understand.** The profiles screen and the detail pane both try
   to display *settings*, so profiles compete with the pipeline for the same job and the
   mental model is muddy.
2. **The loop is invisible as a loop.** The pipeline is shown as a flat list of phases.
   There is no depiction of the actual control flow — the outer iterate-until-clear loop,
   or the inner `inner_check_retries` loop (checks → remediation). Both are buried in
   config fields.

The operator's dominant workflow is **overnight, pre-PR codebase hardening — loop until
clear** — so the run/monitor surface matters as much as authoring. Profiles are the
"save game" for settings, and prompt management is a known growth area (prompts are
fragment-composed and vary by harness *and* model).

## 2. Goals / Non-goals

**Goals**
- Make the **loop** the centre of gravity: an editable vertical diagram that truthfully
  depicts the active control flow (outer loop, inner check-retry loop, disabled phases).
- Allow editing harness / model / effort / timeout / prompt **directly from the loop**,
  including triage's nested routes table.
- Reuse the loop diagram as the **live run/monitor** view (same shape, two modes).
- Demote **profiles** to a clean save/load picker.
- Keep a **prompts library** for curation, with in-loop prompt picking for the common case.
- Move to **real interactive Textual widgets** (focus, selection, mouse + keyboard).

**Non-goals**
- Loop **reordering / topology editing** (not a CLI capability; out of scope).
- Replacing profile persistence semantics. TUI writes use the same profile edit library
  used by the CLI (`profiles.save_profile_raw` / `config set`); the TUI does not invent
  a separate config format or hidden run-only overrides.
- A standalone visual prompt-fragment composer (future roadmap; this design only reserves
  the library surface).

## 3. Design principles

1. **The loop diagram is the spine of the app** — the same vertical diagram is used to
   *author* a loop and to *watch* it run. One mental model, two modes.
2. **The diagram is config-truthful.** What you see always equals what the profile will
   do: inner rail only drawn when `inner_check_retries > 0`; disabled phases dim and drop
   out of the data flow; `final review` only shown when enabled.
3. **Edit where you see it.** Summary always visible per phase; the focused phase expands
   in place to edit. Single fields edit inline; large content (prompts, route rows) opens
   a focused modal.
4. **CLI-equivalence is preserved.** The TUI launches runs and writes config through the
   same profile edit library as the CLI; `assert_equivalent_run_artifacts` parity is maintained. `render_shell_text`
   is retained as a headless fallback derived from the same state, but is no longer the
   load-bearing render path.
5. **Profiles are the save layer, not the settings layer.** They load settings into the
   loop and save the current loop; they never try to display full settings.

## 4. Architecture

### 4.1 Render strategy
Replace the "render screens to text lines into `Static`" approach with genuine Textual
widgets. The existing pure functions in `tui_state.py` (`pipeline_phases`, `profile_view`,
`run_monitor_view`, etc.) remain the **view-model layer** — they already compute exactly
the data each widget needs. Widgets consume those view-models; they do not read profiles
directly.

```
profiles.Profile / run records
        │  (pure functions, unchanged)
        ▼
tui_state view-models  ──►  Textual widgets (interactive)   [primary path]
        │                                                     keyboard + mouse
        └────────────────►  render_shell_text(...)           [headless fallback]
```

### 4.2 Edit path — working copy + explicit save (PREREQUISITE)

**Shipped prerequisite.** Plan 1 added both the non-interactive
`revrem config set <profile> <key> <value>` path and the library writer
`profiles.save_profile_raw(name, authored_delta, ...)`. The TUI uses the library writer
in-process so loop edits can remain an explicit-save working copy rather than one disk
write per keystroke.

**Chosen model: working copy + explicit save.** This fits the operator's stated mental
model ("profiles are the save game").

1. The TUI loads a profile into an **in-memory working copy**. Inline edits mutate the
   working copy only — no CLI call per keystroke. A `*` marks unsaved changes.
2. **Save → profile** persists the whole working copy in one write, via
   `profiles.save_profile_raw(name, authored_delta, ...)`. Plan 1 also shipped
   `revrem config set <profile> <key> <value>` for scriptable one-shot edits, but the
   TUI deliberately does not use the immediate-persist path because auto-persist
   conflicts with the "save game" model.
3. **Run** and **dry-run** execute the validated working copy without persisting it.
   The CLI receives an exact generated `--profile-snapshot`, retained with live-run
   artifacts for reproducibility. Saving remains explicit, and bundled profiles can
   be run without weakening their read-only persistence contract.

The working copy stores raw profile TOML keys (`pipeline.max_iterations`,
`review.model`, `commit.message_model`, etc.) so saved profiles round-trip through the
same parser and serializer as CLI edits.

### 4.3 Optional-dependency posture
Textual remains an optional `[tui]` extra. The lazy-import / fallback scaffolding in
`tui.py` (`_TextualComponents`, `_TextualFallbackApp`) is retained; when Textual is absent,
`render_shell_text` provides the headless view.

## 5. Screens

Navigation: **`1 Loop · 2 Run · 3 Profiles · 4 Prompts`** (Loop first). A stable
two-line app bar shows only repository, workspace, live state, and workspace
navigation. The Loop workspace begins with a concise labelled **Next Run**
summary for profile, review input, provenance, and launch command, followed by
an editable **Run Settings** card for base, maximum outer iterations, and
final-review state. It always says whether the next
run has an initial-review file. Compatible review is preselected; an actionable
review from a different Git state remains visible but requires an explicit
validation choice. Current-phase actions render inside the expanded owning
phase. The diagram is segmented into a loop summary band, numbered phase
bands, explicit inner-retry and outer-loop return bands, and an optional final
review marker. Bottom bar: live state plus the shortest contextual key strip.
`revrem ui` may briefly show a splash screen while Textual mounts; operators can
skip it with `--skip-splash`. The splash is terminal-native retro text art, not
a bitmap asset, so it works in plain terminal sessions. When a compatible prior
run exists, the Loop screen seeds its working copy from the structured
`summary.resume_config` contract rather than the redacted display command. A
single Loop session owns the loaded profile, draft, provenance, pending-review
availability, and launch plan, so the Next Run summary, diagram, save target,
preview, and run cannot disagree.

Textual mounts an I/O-free first frame before catalog, profile, history, and
review discovery. Background work returns one complete bootstrap result;
composition does not perform discovery or mutate the active profile. The UI
installs that result on Textual's thread, recomposes, and activates exactly one
workspace only after replacement widgets are mounted. Branding remains briefly
visible when enabled, a key can dismiss it without hiding unfinished loading,
and startup reports a slow-load state after ten seconds rather than exposing an
incomplete workbench. An explicit `--profile` always takes precedence over
last-run replay.

### 5.1 Loop (centerpiece)

Vertical accordion. Each phase shows a one-line summary always; the focused phase expands
in place. `●`/`○` = enabled/disabled (space toggles). The left gutter draws the loop
rails; arrows carry their real exit condition and bound.

Checks is always enabled because RevRem always runs its built-in worktree-cleanliness
check. Its card distinguishes that mandatory check from configured commands, offers
repository-detected and recent repo-local command sets through a selector, and owns the
check-failure retry setting. Full help is a scrollable modal; the footer remains a short
contextual action strip and never flattens escaped markup.

Flat phase focused (review):

```
┌─ LOOP · default ──────── base main · max 11 · stop when clear · inner-check retries: 2 ───┐
│                                                                                           │
│  ┌▶ ▼ review ◀ ──────────────────────────────────────────── codex · gpt-5.5 · med · 600s │
│  │     harness ‹ codex ›   model ‹ gpt-5.5 ›   effort ‹ medium ›   timeout ‹ 600s ›       │
│  │     prompt  built-in review (codex)        [↵ pick · e edit]                           │
│  │                                                                                         │
│  │     ○ triage ──────────────────────────────────────────────────────────────── off ─── │
│  │  ┌▶ ● remediation ─────────────────────────────────── codex · gpt-5.4-mini · med · 600s│
│  │  │  ● checks ───────────────────────────────────────────────────────────── 2 commands │
│  │  └◀─ checks failed → remediation   (up to 2 inner retries)                             │
│  │     ● commit ───────────────────────────────────────────── codex · gpt-5.3-spark · 300s│
│  └◀──── not clear & iteration < 11 → review                                                │
│                                                                                           │
│  ⚑ final review  (runs once when the loop ends) ─────────────────── codex · gpt-5.5 · med │
└───────────────────────────────────────────────────────────────────────────────────────────┘
 ↑↓ phase · space enable · ↵ expand/edit · e prompt · r run · d dry-run · s save→profile · ? help
```

Triage focused & ON — the discriminating case; expands into its nested routes table:

```
│  ▼ triage ◀ ──────────────────────────────────────────── codex · routes: 3 · default→remed.│
│    routing   default ‹ remediation ›   strict ‹ off ›   escalate-model ‹ on ›             │
│    ┌ routes ────────┬───────────┬────────┬───────┬───────────┬─────────────┐             │
│    │ ▸ security   codex │ gpt-5.5  │ high  │ 600s │ read-only │ remediation │             │
│    │   correctness codex│ gpt-5.4  │ med   │ 600s │ read-only │ remediation │             │
│    │   nit        claude│ haiku-4.5│ low   │ 300s │ none      │ drop        │             │
│    └────────────────┴───────────┴────────┴───────┴───────────┴─────────────┘             │
│    [↵ edit route · a add]                                                                  │
```

Interaction:
- Single fields (harness, model, effort, timeout) edit **inline** (cycle/`‹ ›` select or
  small inline input).
- **Prompt** is harness-aware: codex `review` shows `built-in review (codex)`; other
  harnesses show the selected prompt/fragments. `↵ pick` opens the library picker; `e`
  opens a prompt-edit modal.
- **Route rows** edit in a focused modal (`↵ edit route`); `a` adds routes.
  Route deletion is deferred until the profile-save primitive can express
  key removal instead of merge-only writes.
- Disabled phases render dimmed and drop out of the rails.

### 5.2 Run / monitor

The same diagram, live. `✓` done · `▶` running · `·` pending · `⤫` disabled. Iteration and
inner-retry counters ride on the loop arrows.

```
┌─ RUN · default ──────────────  running · iteration 3 / 11 · 04:12 elapsed ───────────────┐
│                                                                                          │
│  ┌▶ ✓ review        2 findings (not clear)            codex · gpt-5.5 · 0:48             │
│  │     ⤫ triage      disabled                                                             │
│  │  ┌▶ ✓ remediation  2 fixed                          codex · gpt-5.4-mini · 1:30        │
│  │  │  ▶ checks       running 1/2  ▕▰▰▰▱▱▏             pytest · 0:21                       │
│  │  └◀─ inner retry 0 / 2                                                                  │
│  │     · commit       pending                                                             │
│  └◀──── iteration 3 / 11 · not yet clear                                                   │
│                                                                                          │
│  events ─────────────────────────────────────────────────────────────────────────────── │
│   12:31:50  remediation  applied 2 fixes                                                   │
│   12:32:11  checks       running pytest -q …                                               │
│  ──────────────────────────────────────────────────────────────────────────────────────  │
│  artifacts: run-2026…06-27 · 14 files      k stop · l logs/events · o open dir            │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Backed by the existing live-run controller, `events.jsonl`, and artifact/event plumbing.
For the overnight workflow this answers "where is it / how many iterations left / is it
converging" at a glance, with the event tail and artifacts for a morning post-mortem.
The first run-monitor slice deliberately does not expose pause/resume: the controller has
stop/cancel semantics but no pause primitive, so advertising pause would create a false
operator contract.

### 5.3 Profiles (save / load)

A picker, not a settings editor. Each row: identity + one-line loop summary. Light grouping
separates the operator's saves from preset starting points.

```
┌─ PROFILES ─────────────────────────────────────────────────────────────────────────────┐
│  load a saved loop · 8 available                                                          │
│                                                                                          │
│  ─ yours ──────────────────────────────────────────────────────────────                 │
│  ▸ default     project  main · 11 iters · 2 checks · triage off     ← loaded              │
│    dogfood     project  main · 3 iters  · 5 checks · triage on                            │
│    final-pr    user     main · 2 iters  · 0 checks                                        │
│  ─ presets ────────────────────────────────────────────────────────────                 │
│    docs        builtin  main · 2 iters · 0 checks                                         │
│    security    builtin  main · 2 iters · 0 checks                                         │
│    refactor    builtin  main · 2 iters · 0 checks    … (3 more)                           │
│                                                                                          │
│  “Saved from RevRem CLI on 2026-05-05”                                                    │
│  ─────────────────────────────────────────────────────────────────────────────────────  │
│  ↵ load into loop · s show · n new · c clone · e edit config · i import · x export · del delete │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

`presets` (builtin) double as the team-guidance mechanism in the roadmap: a recommended
loop you hand to others. Actions shell through `revrem config` as today.

### 5.4 Prompts (library + in-loop picking)

Prompts are fragment-composed (`prompts/fragments/`, `triage_v1/v2.txt`,
`prompts_composer.py`) with trust levels and versioning. Division of labour:

- **In-loop:** harness-aware prompt field — pick from library, quick-edit, or show
  `built-in` for codex review. Covers the 80% case.
- **Library (`4 Prompts`):** curate prompts + fragments, tagged by harness + model, with
  versioning. Home for roadmap features (per-model recommended prompts, swap-on-new-model,
  diffing). This design delivers the **library surface + in-loop picking**; advanced
  curation tooling is reserved, not built here.

## 6. Component breakdown

Each widget consumes a view-model and is independently testable.

| Widget | Purpose | Consumes | Notes |
| --- | --- | --- | --- |
| `LoopDiagram` | vertical accordion + rails; focus/selection | `pipeline_phases()` + loop meta | draws rails from config truth |
| `PhaseCard` | one phase summary + inline expand/edit | `PhaseView` | flat-field editing |
| `TriageRoutesTable` | nested routing + routes table | triage routing/routes | route-row modal |
| `LoopRunView` | live mode of the diagram | `run_monitor_view` + events | status glyphs, counters |
| `EventLog` | scrolling event tail | `run_event_views` | reuses `event_row_text` |
| `ProfilePicker` | grouped save/load list | `profile_view`/snapshot | load / save-current |
| `PromptField` | harness-aware prompt cell | phase + harness caps | picker + edit modal |
| `PromptLibrary` | curate prompts/fragments | prompts inventory | roadmap surface |
| `PromptEditModal`, `RouteEditModal` | focused editors | single item | overlay screens |

State model: a single `TuiShellModel`-style object holds the loaded profile, modified
flag, selected screen/phase, and run state; widgets render from it and emit
profile-edit library / run intents back to the controller.

## 7. Error handling

- Saves that fail validation surface the `save_profile_raw` / profile parser `ValueError`
  inline; the working copy remains dirty so the operator can correct the field.
- Run/monitor degrades gracefully when events are unavailable (existing `event_error`
  path) and when artifacts are missing (existing `exists` flag).
- Missing Textual → headless `render_shell_text`.

## 8. Testing

- **Snapshot tests** for each widget's rendered output (Textual pilot / SVG export) across
  representative profiles: triage off, triage on with routes, `inner_check_retries` 0 vs N,
  final review on/off.
- **Pilot smoke** (`test_tui_pilot_smoke.py`) extended for navigation and inline editing.
- **Bootstrap lifecycle tests** assert that the first completed frame contains exactly one
  workspace, arrow navigation works before a workspace shortcut, and pressing `1` is
  idempotent.
- **CLI-equivalence preserved**: `test_tui_cli_equivalence.py` /
  `assert_equivalent_run_artifacts` must continue to pass — TUI-launched runs equal
  CLI-launched runs.
- **View-model unit tests** stay valuable since widgets consume view-models.

## 9. Open questions / future

- Depth of in-loop prompt editing vs. deferring to the library (resolved direction: pick +
  quick-edit in loop; deep curation in library).
- Prompt library data model for harness×model recommendations (roadmap).
- Whether `presets` editing should be blocked (builtin) vs. clone-to-edit (lean: clone-to-edit).
- Route deletion from the loop editor. The shipped route editor supports edit
  and add; deletion needs a delete-capable profile-save primitive.
```
