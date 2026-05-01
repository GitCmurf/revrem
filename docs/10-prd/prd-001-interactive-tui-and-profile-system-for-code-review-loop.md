---
document_id: REVREM-PRD-001
type: PRD
title: Interactive TUI and Profile System for code-review-loop
status: Draft
version: "0.1"
last_updated: '2026-05-01'
owner: GitCmurf
area: product
docops_version: "2.0"
template_type: prd-standard
template_version: "2.0"
description: Adds a TOML profile system, Rich progress display, and Textual TUI to code-review-loop
keywords:
  - code-review-loop
  - revrem
  - tui
  - profile
  - textual
  - rich
related_ids:
  - REVREM-ADR-001
  - REVREM-DEVEX-001
---

<!-- MEMINIT_METADATA_BLOCK -->

> **Document ID:** REVREM-PRD-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.1
> **Last Updated:** 2026-05-01
> **Type:** PRD

# PRD: Interactive TUI and Profile System for code-review-loop

<!-- MEMINIT_SECTION: title -->

## Table of Contents

<!-- MEMINIT_SECTION: toc -->

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals and Success Metrics](#3-goals-and-success-metrics)
4. [Proposed Solution](#4-proposed-solution)
5. [Requirements](#5-requirements)
6. [Alternatives Considered](#6-alternatives-considered)
7. [Open Questions](#7-open-questions)
8. [Version History](#8-version-history)

---

## 1. Executive Summary

<!-- MEMINIT_SECTION: executive_summary -->

`code-review-loop` today requires operators to re-specify ~10 CLI flags on every invocation, has no
config persistence, and reports progress as plain timestamped stderr lines. This PRD specifies a
three-layer upgrade: a TOML profile system for named, persistent, cross-machine-syncable
configurations; a Rich-powered live progress display; and an optional Textual TUI for interactive
profile management and run monitoring. The CLI surface is preserved unchanged for AI-agent callers;
a new `revrem` entry-point alias is registered for human ergonomics.

---

## 2. Problem Statement

<!-- MEMINIT_SECTION: problem_statement -->

The tool has **26 CLI flags today** with more planned (additional AI harnesses: `claude`, `gemini`,
`opencode`, `kilo`; git-commit behaviours; pluggable prompts). The recommended production invocation
in DEVEX-001 already uses 10 flags. This creates four compounding problems:

1. **No persistence.** Operators must reconstruct the full flag set on every run from memory or
   shell history. There is no `--profile` concept.
2. **No cross-machine parity.** The operator uses a laptop and two desktop machines; configs diverge
   silently.
3. **Opaque progress.** Progress is plain `HH:MM:SS|rev|1   | start: codex review …` text on
   stderr. There is no visual phase tracker, elapsed timing, or finding preview.
4. **Invisible pipeline.** The review → remediate → check → final-review loop structure can only be
   understood by reading source code or the README. There is no interactive way to inspect or adjust
   it.

---

## 3. Goals and Success Metrics

<!-- MEMINIT_SECTION: goals -->

### Goals

- G1: Operators configure a run once and invoke it by name on any machine.
- G2: Progress during a run is visually scannable without reading raw log lines.
- G3: The pipeline structure is inspectable and adjustable without editing source code.
- G4: The CLI surface for AI agents is unchanged; new capabilities are purely additive.
- G5: Config files are plain text, diffable, and syncable via a dotfiles git repo.

### Success Metrics

| Metric | Target | Measurement |
|---|---|---|
| Flags required to start a common run | 1 (`--profile NAME`) | Manual test |
| Cross-machine config sync | Works on laptop + 2 desktops via symlink | Manual smoke test |
| New harness addable | ≤ 1 new file + 1 config key | Code review of first addition |
| Agent-facing CLI unchanged | All 26 existing flags accepted, behaviour identical | Existing test suite green |
| Progress display renders during dry-run | Rich panel visible | Manual test |

---

## 4. Proposed Solution

<!-- MEMINIT_SECTION: solution -->

Three layers, each independently useful and backwards-compatible with the layer below it.

### Layer 1 — TOML Profile System (always installed)

Named profiles stored in `~/.config/code-review-loop/profiles.toml`. A second config location,
`.crl.toml` in the project root, allows per-repository overrides. All 26 existing CLI flags remain
available as ad-hoc overrides on top of any profile.

**Config resolution order (last wins):**

```
~/.config/code-review-loop/profiles.toml  ← user-global named profiles
.crl.toml (project root)                  ← project-local overrides
--profile NAME                            ← select a named profile
individual CLI flags                       ← ad-hoc overrides
```

**TOML profile schema:**

```toml
[profiles.final-pr]
description = "Full PR readiness check"

[profiles.final-pr.pipeline]
base            = "main"
max_iterations  = 2
final_review    = true

[[profiles.final-pr.pipeline.checks]]
command = "pytest -q"

[[profiles.final-pr.pipeline.checks]]
command = "git diff --check"

[profiles.final-pr.review]
harness           = "codex"   # extensible: "claude" | "gemini" | "opencode" | "kilo"
model             = "gpt-5.5"
reasoning_effort  = "medium"
timeout_seconds   = 1800

[profiles.final-pr.remediation]
harness           = "codex"
model             = "gpt-5.4-mini"
reasoning_effort  = "medium"
timeout_seconds   = 1800

[profiles.final-pr.output]
summary_format          = "both"
debug_status_detection  = true
progress_style          = "compact"
```

**`revrem config` subcommands:**

| Subcommand | Action |
|---|---|
| `revrem config list` | Table of profiles with descriptions and last-used timestamps |
| `revrem config show NAME` | Pretty-print one profile |
| `revrem config new` | Interactive wizard (prompts only, no TUI required) |
| `revrem config edit NAME` | Opens profile in `$EDITOR` |
| `revrem config delete NAME` | Removes profile with confirmation prompt |
| `revrem config export NAME` | Writes portable TOML to stdout |
| `revrem config import FILE` | Merges a portable TOML into user config |

**Entry points registered:**

```toml
[project.scripts]
code-review-loop = "code_review_loop.cli:main"   # existing — unchanged
revrem           = "code_review_loop.cli:main"   # new alias
```

### Layer 2 — Rich Progress Display (optional extra `[progress]`)

Replaces the `progress_log` / `progress_event` / `progress_continuation` stderr functions with a
`ProgressManager` using `rich.live.Live`. The display updates in-place rather than appending lines.
If `rich` is not installed the existing plain-text fallback is used transparently.

Indicative display during a run:

```
┌─ revrem ────────────────────────────────────────────────────────┐
│  Profile: final-pr    Base: main    Iteration: 1 / 2   ⏱ 00:23 │
│                                                                  │
│  ✓ Review       done      00:18  gpt-5.5    findings (2)        │
│  ● Remediate    running   00:05  gpt-5.4-mini                   │
│  ○ Check        waiting         pytest -q · git diff --check    │
│  ○ Final review waiting                                          │
└──────────────────────────────────────────────────────────────────┘
  [P1] Missing null check in parse_args line 42
  [P2] Unused import in cli.py
```

### Layer 3 — Textual TUI (optional extra `[tui]`)

`revrem` with no arguments (or `revrem ui`) launches the TUI. Four keyboard-driven screens:

| Screen | Contents |
|---|---|
| **Home** | Recent runs table (timestamp, profile, status, duration); quick-run buttons |
| **Profiles** | Table of all profiles; New / Edit / Clone / Delete / Export actions |
| **Pipeline Builder** | Per-profile step list with enable/disable toggles, harness selector, model, timeout, editable checks list |
| **Run Monitor** | Embedded Rich phase panel + scrollable log pane; launched from Home or Profiles |

`rich` and `textual` are never imported on the critical CLI path; both are imported inside their
respective entry points only, so bare `code-review-loop` invocations carry zero new overhead.

### Cross-machine Sync

Config lives at `~/.config/code-review-loop/`. On Linux/WSL2:

```bash
mkdir -p ~/dotfiles/code-review-loop
ln -s ~/dotfiles/code-review-loop ~/.config/code-review-loop
```

`~/dotfiles/` is a git repo; pushing syncs configs across all machines. Windows path is
`%APPDATA%\code-review-loop\`; git-bash operators can use the same `~/.config/` path.

---

## 5. Requirements

<!-- MEMINIT_SECTION: requirements -->

### Functional Requirements

**Must have:**

- [FR-1] Named TOML profiles with the schema defined in §4
- [FR-2] Config resolution order: user global → project `.crl.toml` → `--profile` → CLI flags
- [FR-3] `revrem config` subcommands: `list`, `show`, `new`, `edit`, `delete`, `export`, `import`
- [FR-4] `--profile NAME` flag on `revrem run` and on bare `revrem [flags]` (backwards-compatible)
- [FR-5] All 26 existing CLI flags work as overrides on top of any profile
- [FR-6] Rich in-place progress display when `[progress]` extra is installed
- [FR-7] Graceful degradation to existing plain-text progress when Rich is absent
- [FR-8] `revrem` entry-point alias registered alongside `code-review-loop`
- [NFR-1] Zero change to agent-facing CLI behaviour
- [NFR-2] `tomllib` (stdlib ≥ 3.11) for TOML reading; `tomli-w` as the only new required runtime dep
- [NFR-3] `rich` and `textual` are optional extras; never imported on the critical CLI path

**Should have:**

- [FR-9] Textual TUI with four screens (Home, Profiles, Pipeline Builder, Run Monitor)
- [FR-10] Run history index at `~/.local/share/code-review-loop/runs.json`
- [FR-11] Harness registry abstraction (codex today; pluggable for claude/gemini/opencode/kilo)

**Could have:**

- [FR-12] `revrem config sync` for explicit dotfiles push/pull (deferred; symlink approach preferred)
- [FR-13] Profile import from a URL

### Non-Functional Requirements

- [NFR-4] TUI must work on WSL2 Ubuntu (primary) and Windows git-bash (secondary)
- [NFR-5] `./scripts/dev-check` (ruff + mypy + pytest) must stay green at every step
- [NFR-6] All new code follows the existing atomic-unit rule: code + docs + tests together

---

## 6. Alternatives Considered

<!-- MEMINIT_SECTION: alternatives -->

- **Option A — Enhanced CLI only (no TUI):** Config persistence and Rich progress are delivered but
  there is no visual pipeline editor and no interactive profile management. Rejected because the
  "premium DevEx feel" goal and the pipeline-inspection requirement are unmet.

- **Option C — Local Web UI (React + local server):** Highest design ceiling (true node-graph
  pipeline editor via React Flow); rejected because it introduces a Node/React build chain, requires
  two processes to manage, and is disproportionate for a solo-operator tool. Could be revisited if
  team use is ever in scope.

---

## 7. Open Questions

<!-- MEMINIT_SECTION: open_questions -->

- [Q1] ✅ Resolved — `revrem` registered as alias alongside `code-review-loop` (both installed).
- [Q2] ✅ Resolved — `tomli-w` required (profile system); `rich` + `textual` bundled together in a
  single `[tui]` optional extra. Agents install bare; humans install `[tui]`. `dev` extra includes
  both.
- [Q3] Windows baseline: WSL2 is the tested primary target. Git-bash on Windows is the secondary
  path. CI will run on Linux only for now.

---

## 8. Version History

<!-- MEMINIT_SECTION: version_history -->

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-01 | GitCmurf | Initial draft |
