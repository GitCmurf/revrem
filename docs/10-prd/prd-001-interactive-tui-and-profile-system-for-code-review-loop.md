---
document_id: REVREM-PRD-001
type: PRD
title: Interactive TUI and Profile System for code-review-loop
status: Draft
version: "0.7"
last_updated: '2026-05-02'
owner: GitCmurf
area: product
docops_version: "2.0"
template_type: prd-standard
template_version: "2.0"
description: "Defines the staged revrem product upgrade: stable local distribution, TOML profiles, rich progress, and an optional Textual TUI"
keywords:
  - code-review-loop
  - revrem
  - distribution
  - profile
  - textual
  - rich
related_ids:
  - REVREM-ADR-001
  - REVREM-DEVEX-001
  - REVREM-TEST-001
---

<!-- MEMINIT_METADATA_BLOCK -->

> **Document ID:** REVREM-PRD-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.7
> **Last Updated:** 2026-05-02
> **Type:** PRD

# PRD: Interactive TUI and Profile System for code-review-loop

<!-- MEMINIT_SECTION: title -->

## Table of Contents

<!-- MEMINIT_SECTION: toc -->

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals and Success Metrics](#3-goals-and-success-metrics)
4. [Scope and Non-Goals](#4-scope-and-non-goals)
5. [Proposed Solution](#5-proposed-solution)
6. [Architecture and Quality Bar](#6-architecture-and-quality-bar)
7. [Requirements](#7-requirements)
8. [Delivery Plan](#8-delivery-plan)
9. [Acceptance and Verification](#9-acceptance-and-verification)
10. [Alternatives Considered](#10-alternatives-considered)
11. [Resolved Decisions and Open Questions](#11-resolved-decisions-and-open-questions)
12. [Version History](#12-version-history)

---

## 1. Executive Summary

<!-- MEMINIT_SECTION: executive_summary -->

`code-review-loop` is moving from a proven local script extraction to a durable local product named
`revrem`. The product must support two distinct operator modes:

- **Development mode:** this repository remains the editable testbed, installed in `./.venv` with
  dev extras and full checks.
- **Stable mode:** all other repositories run the last promoted version through launchers in
  `~/.local/bin`, backed by an isolated stable virtualenv under `~/.local/share/revrem/`.

This PRD defines the staged work after that distribution boundary: TOML profiles, a Rich progress
surface, and an optional Textual TUI. The design keeps the existing `code-review-loop` CLI contract
stable for agents while adding `revrem` as the human-facing alias and product namespace.

---

## 2. Problem Statement

<!-- MEMINIT_SECTION: problem_statement -->

The current tool is usable but still too operationally manual for repeated PR-readiness work:

1. **Installation drift:** the original Meminit-local script can fall out of sync with the standalone
   utility. Other repos need a stable command that is not implicitly coupled to active development
   edits in this checkout.
2. **Flag repetition:** the recommended final command already uses ten flags. Operators must
   reconstruct model, timeout, base, summary, and check settings from shell history or docs.
3. **No profile lifecycle:** there is no native way to create, inspect, export, or reuse named
   review/remediation configurations.
4. **Limited run observability:** compact progress logs are useful for watched terminals, but long
   review/remediation runs need clearer phase state, elapsed time, findings preview, and artifact
   locations.
5. **Pipeline opacity:** the review -> remediate -> check -> final-review loop is testable in code,
   but not inspectable or adjustable as an operator workflow.

The product must solve these without weakening the original strengths: dependency-light runtime,
bounded nested Codex execution, deterministic artifacts, plain shell compatibility, and strong tests.

---

## 3. Goals and Success Metrics

<!-- MEMINIT_SECTION: goals -->

### Goals

- G1: Keep development and stable installs intentionally separate.
- G2: Let an operator run a common PR-readiness loop by profile name from any local repo.
- G3: Preserve the current `code-review-loop` flags and behavior for agent callers.
- G4: Make run progress and close-down state visibly reliable, especially when review output goes
  clear or status detection is uncertain.
- G5: Keep configuration plain-text, diffable, and suitable for dotfiles synchronization.
- G6: Add UI capabilities through optional extras, with zero import or dependency cost on the
  minimal CLI path.

### Success Metrics

| Metric | Target | Measurement |
|---|---|---|
| Stable command availability | `code-review-loop` and `revrem` resolve from `~/.local/bin` in other repos | Manual smoke test from `../Meminit` |
| Development isolation | Active edits are visible only through `./.venv/bin/code-review-loop` until promoted | Manual smoke test |
| Flags required for common run | `revrem --profile final-pr` | CLI integration test |
| Existing CLI compatibility | Existing test suite green without changing current flag behavior | `./scripts/dev-check` |
| Status close-down reliability | Clear final review exits `0` with `stopped_reason=review_clear` | Unit regression test |
| Optional UI isolation | Bare install imports no `rich` or `textual` modules | Unit/import test |

---

## 4. Scope and Non-Goals

<!-- MEMINIT_SECTION: scope -->

### In Scope

- Stable promotion script from this checkout into a shared local virtualenv.
- `revrem` console-script alias alongside `code-review-loop`.
- TOML profile loading, validation, merging, and CLI overrides.
- `revrem config` subcommands for profile lifecycle management.
- Rich progress display behind an optional extra.
- Textual TUI behind an optional extra.
- Run history metadata under `~/.local/share/revrem/`.
- Optional checkpoint commits after verified remediation passes.

### Non-Goals

- Network service, daemon, or browser UI.
- Multi-user server deployment.
- Secret storage or credential management.
- Automatic pushes, branch creation, or remote repository mutation.
- Implementing non-Codex execution backends; Claude, Gemini, opencode, and Kilo
  remain reserved profile syntax until their headless adapters are implemented
  and tested.

---

## 5. Proposed Solution

<!-- MEMINIT_SECTION: solution -->

### Phase 0: Development and Stable Distribution

The repository owns two installation paths:

| Mode | Command | Target | Purpose |
|---|---|---|---|
| Development | `./scripts/install-dev` | `./.venv` | Editable install with dev tooling for implementation work in this repo |
| Stable | `./scripts/promote-stable` | `~/.local/share/revrem/releases/<timestamp>` plus `stable-venv` | Validated source snapshot for every other local repo |

`scripts/promote-stable` runs `./scripts/dev-check` before promotion unless
`REVREM_SKIP_CHECKS=1` is explicitly set. It copies the source into a timestamped release directory,
ensures a stable virtualenv exists for the Python interpreter, and updates these launchers:

```text
~/.local/bin/code-review-loop
~/.local/bin/revrem
```

This gives operators a clear promotion gate: experiment through `./.venv/bin/...`, then deliberately
promote the tested version for cross-repo use.

### Phase 1: TOML Profile System

Profiles live at `~/.config/revrem/profiles.toml`. Project-local defaults live in `.revrem.toml` at
the target repository root. User-global config is appropriate for model defaults and operator
preferences; project-local config is appropriate for base branch, checks, and repo-specific artifact
settings.

**Resolution order, last wins:**

```text
built-in defaults
~/.config/revrem/profiles.toml selected profile
.revrem.toml project defaults and selected profile overrides
individual CLI flags
```

Selected profile names must exist in user or project config before defaults are applied, so a
misspelled `--profile` fails fast instead of silently falling back to defaults. A configured
`timeout_seconds = 0` remains a valid disable signal after profile resolution and reaches the
matching phase subprocess unchanged. If a phase omits `timeout_seconds`, it uses the built-in
default timeout rather than inheriting the sibling phase's value.

**Profile schema:**

```toml
[profiles.final-pr]
description = "Full PR readiness check"

[profiles.final-pr.pipeline]
base = "main"
max_iterations = 2
final_review = true

checks = [
  "pytest -q",
  "git diff --check",
]

[profiles.final-pr.review]
harness = "codex"
model = "gpt-5.5"
reasoning_effort = "medium"
timeout_seconds = 1800

[profiles.final-pr.triage]
enabled = true
harness = "codex"
model = "gpt-5.4-mini"
reasoning_effort = "low"
timeout_seconds = 300
prompt = "Break down the review into confirmed actions, likely false positives, and verification steps."

[profiles.final-pr.remediation]
harness = "codex"
model = "gpt-5.4-mini"
reasoning_effort = "medium"
timeout_seconds = 1800

[profiles.final-pr.commit]
enabled = false
message_model = "gpt-5.3-codex-spark"
message_prompt = "Write one concise git commit subject for the staged RevRem remediation changes."

[profiles.final-pr.output]
summary_format = "both"
debug_status_detection = true
progress_style = "compact"
```

### Phase 2: `revrem config`

`revrem config` is a non-TUI management surface that works in plain terminals and from agent
automation:

| Subcommand | Required behavior |
|---|---|
| `list` | Print profile name, description, source file, and last-used timestamp |
| `show NAME` | Print the resolved profile as TOML or JSON |
| `new NAME` | Create a minimal profile, refusing to overwrite without `--force` |
| `edit NAME` | Open the owning config file in `$EDITOR` |
| `delete NAME` | Remove profile after confirmation or with `--yes` |
| `export NAME` | Write portable TOML to stdout |
| `import FILE` | Validate and merge imported profiles |
| `doctor` | Explain config paths, selected profile, and merge result |

### Phase 3: Run History and Progress Renderer

Each non-dry-run invocation appends one compact metadata record to
`~/.local/share/revrem/runs.jsonl`, or `$XDG_DATA_HOME/revrem/runs.jsonl` when
`XDG_DATA_HOME` is set. This file is append-only JSONL so interrupted or
partially failed runs still leave existing history readable. The record stores
the run id, timestamps, cwd, base, selected profile, final status, iteration
count, and artifact pointers; it does not duplicate review/remediation
transcripts.

The current `progress_event` shape remains the internal contract. A progress
renderer interface receives the same phase events and emits either compact text
or Rich live output. Rich is activated only when installed and requested;
compact text remains the default for scripts and logs.
Compact, verbose, and Rich progress timestamps use local terminal wall time for
watched runs. Persisted run-history timestamps remain UTC ISO-8601 values.

Optional Codex triage is implemented as a read-only interpretative phase between
review and remediation. It exists to turn review prose and check failures into a
small action plan that a cheaper remediation model can execute. The triage
artifact is stored as `triage-N.txt`; remediation receives both the triage
handoff and the original review/check context. Non-Codex triage harness names
remain valid configuration syntax for management commands but are rejected on
the executable path until their adapters exist.

Optional commit-after-remediation is implemented as a separate post-check phase.
Remediation agents do not own git history. After checks pass, RevRem may stage
the current worktree with `git add -A` while excluding the configured artifact
directory, skip clean trees, optionally ask a read-only Codex invocation for a
concise subject, normalize default subjects to Conventional Commit syntax with
an appended ` (RevRem)`, and run `git commit` deterministically. A CLI
`--commit-message-prompt` override intentionally disables that default subject
policy. This keeps commits reproducible and preserves a future path for cheaper
commit-message models without coupling history mutation to the remediation
prompt.

### Phase 4: Textual TUI

`revrem ui` launches a Textual app with four screens:

| Screen | Contents |
|---|---|
| Home | Recent runs, profile quick-start, current stable/dev version information |
| Profiles | Profile table with New, Edit, Clone, Delete, Export, Import |
| Pipeline Builder | Ordered phase list, checks editor, model selectors, timeout controls |
| Run Monitor | Rich phase state, scrollable log, artifact links, final summary |

The TUI shells out to the same tested core functions used by the CLI. It does not own remediation
logic. It consumes dependency-free view models for profile discovery, harness
metadata, recent run history, phase summaries, and profile command previews so
interactive widgets cannot drift from CLI semantics.

---

## 6. Architecture and Quality Bar

<!-- MEMINIT_SECTION: architecture -->

Implementation must preserve these boundaries:

- `cli.py` remains a thin orchestration layer around argument parsing and `LoopConfig`.
- Profile loading and validation live in a separate module, for example
  `src/code_review_loop/profiles.py`.
- Progress rendering lives behind a small interface, for example
  `src/code_review_loop/progress.py`, with compact and Rich implementations.
- TUI view state lives behind `src/code_review_loop/tui_state.py` so Textual
  widgets consume reusable profile, history, pipeline, and harness view models
  rather than reimplementing CLI orchestration.
- Shared run history lives behind `src/code_review_loop/run_history.py`; loop
  orchestration writes per-run artifacts first and then appends compact shared
  metadata from the top-level CLI.
- Commit creation is a deterministic local phase after successful checks.
  Agent/model calls may draft the subject but must not perform staging,
  committing, or pushing.
- Reasoning-effort selection is phase-local: review, triage, remediation, and
  commit-message drafting can each be overridden independently from the CLI.
- Harness execution lives behind `src/code_review_loop/harnesses.py`. Codex is
  the only implemented adapter; reserved adapters for Claude, Gemini, opencode,
  and Kilo deliberately fail if execution is requested while remaining valid
  management/config syntax.
- Optional dependencies are imported inside feature entry points only.
- Config writes are atomic and never mutate files outside the selected config path.
- Errors produce actionable messages and still write summary artifacts where a loop has started.

The quality bar for every phase is:

- Code, docs, and tests land together.
- No unbounded nested agent execution by default.
- No global process state mutation for config, progress, filesystem, or subprocess behavior.
- Unit tests cover merge precedence, edge cases, and failure modes.
- Integration tests cover at least one dry run through the public console entry point.
- `./scripts/dev-check`, `meminit check --format json`, and `git diff --check` pass before stable
  promotion.

---

## 7. Requirements

<!-- MEMINIT_SECTION: requirements -->

### Functional Requirements

- [FR-1] Provide `scripts/install-dev` for editable development setup.
- [FR-2] Provide `scripts/promote-stable` for validated stable local promotion.
- [FR-3] Register `revrem` as an alias for the existing CLI entry point.
- [FR-4] Add `--profile NAME` without changing existing flag semantics.
- [FR-5] Load and validate `~/.config/revrem/profiles.toml`.
- [FR-6] Load `.revrem.toml` from the target repository root.
- [FR-7] Apply config precedence exactly as defined in section 5.
- [FR-8] Implement `revrem config list/show/new/edit/delete/export/import/doctor`.
- [FR-9] Record run metadata under `~/.local/share/revrem/runs.jsonl`.
- [FR-10] Support compact text progress and optional Rich live progress.
- [FR-11] Support optional verified checkpoint commits after remediation passes.
- [FR-12] Implement `revrem ui` behind the `[tui]` extra.

Milestone status as of version 0.7:

- FR-1 through FR-8 are implemented.
- FR-9 is implemented.
- FR-10 is partially implemented: compact progress remains the default and
  `--progress-style rich` activates optional Rich rendering when the `progress`
  extra is installed. Full live Rich layout remains part of the TUI-facing work.
- FR-11 is implemented for Codex commit-message drafting with deterministic
  local git staging and commit execution after checks pass. Default commit
  subjects are normalized to Conventional Commit syntax and suffixed with
  ` (RevRem)` unless the operator provides a custom commit-message prompt.
- FR-12 is partially implemented: `revrem ui` now resolves to a dependency-
  gated Textual entry point with a clean install hint when the optional `tui`
  extra is absent. The current shell renders reusable profile, history, harness,
  phase, and command-preview state. Full interactive screen behavior remains
  pending.
- Codex triage is implemented; non-Codex harnesses remain reserved syntax and
  executable command planning fails fast when an unimplemented backend is
  selected.

### Non-Functional Requirements

- [NFR-1] Existing `code-review-loop` invocations remain valid.
- [NFR-2] Bare runtime remains dependency-light; optional UI dependencies stay optional.
- [NFR-3] TOML reads use `tomllib`; TOML writes may add a small dedicated dependency.
- [NFR-4] Linux/WSL2 is the primary supported environment.
- [NFR-5] Shell scripts are POSIX `sh` compatible.
- [NFR-6] All generated artifacts remain under target-repo `tmp/` unless explicitly configured.
- [NFR-7] Stable promotion must be explicit; no test command may silently update
  `~/.local/bin`.

---

## 8. Delivery Plan

<!-- MEMINIT_SECTION: delivery_plan -->

### Milestone 0: Local Distribution Boundary

Deliverables:

- `revrem` console alias.
- `scripts/install-dev`.
- `scripts/promote-stable`.
- README and DEVEX installation guidance.
- Packaging tests for entry points and script executability.

Done when:

- `./scripts/install-dev` produces `./.venv/bin/code-review-loop` and `./.venv/bin/revrem`.
- `./scripts/promote-stable` produces `~/.local/bin/code-review-loop` and `~/.local/bin/revrem`.
- Running `code-review-loop --dry-run --quiet-progress` from another repo uses the stable install.

### Milestone 1: Profiles

Deliverables:

- Profile dataclasses or typed dictionaries.
- TOML parser and validator.
- Merge engine with explicit precedence tests.
- `--profile` flag and resolved-config diagnostics.
- DEVEX examples for global and project-local profiles.

Done when:

- `revrem --profile final-pr --dry-run --summary-format json` resolves the expected command shape.
- Invalid profiles fail before any Codex subprocess starts.

### Milestone 2: Config Commands

Deliverables:

- `revrem config` command group.
- Atomic config writes.
- Export/import tests.
- `doctor` output suitable for operators and agents.

Done when:

- A profile can be created, shown, exported, deleted, imported, and used in one temp-home test.

### Milestone 3: Run History and Progress Renderer

Deliverables:

- Append-only run metadata under `~/.local/share/revrem/runs.jsonl`, respecting
  `$XDG_DATA_HOME` when present.
- `revrem history list` for recent run inspection.
- `--no-run-history` opt-out for sensitive one-off local runs.
- Optional read-only Codex triage phase with `triage-N.txt` artifacts.
- Renderer interface.
- Compact renderer preserving current output.
- Rich renderer behind optional extra.
- Optional commit-after-remediation phase with post-check gating, skipped clean
  trees, read-only commit-message drafting, and commit-failure summary
  artifacts.
- CLI overrides for review, triage, remediation, and commit-message drafting
  reasoning effort.
- Behavioral tests for history writes, opt-out, newest-first reads, and phase
  transitions.

Done when:

- Non-dry-run CLI invocations append one compact history record after the
  per-run summary artifact is written.
- Dry runs and `--no-run-history` leave shared history untouched.
- Triage-enabled Codex profiles run review -> triage -> remediation -> checks
  without allowing the triage phase to edit files.
- Commit-after-remediation runs only after checks pass and records commit
  artifacts or failure summaries without hiding the run state.
- A no-op remediation with passing checks and no staged changes stops the loop
  immediately; a clear review status exits successfully, while an unknown
  review status remains a conservative non-clear terminal result with
  unexpected-status diagnostics.
- Existing progress tests pass unchanged or with intentional fixture updates.
- Rich mode degrades cleanly when the extra is absent.

### Milestone 4: TUI

Deliverables:

- `revrem ui` entry point.
- Optional `tui` extra declaring Textual without adding default runtime
  dependencies.
- Dependency-free TUI state module for Home/Profile/Pipeline/Run Monitor data.
- Home, Profiles, Pipeline Builder, and Run Monitor screens.
- TUI smoke tests with dependency-guarded execution.
- Screenshots or recorded terminal demo artifacts for PR review.

Initial slice done when:

- `revrem ui --dry-run` succeeds without Textual installed.
- `revrem ui` exits cleanly with an installation hint when Textual is absent.
- TUI state tests cover profile discovery, run-history loading, harness
  metadata, pipeline phase modeling, and profile command previews without
  importing Textual.
- A dependency-guarded launch smoke test proves the Textual app can render the
  home snapshot when Textual is available.
- The default development gate remains free of Textual imports.

Full milestone done when:

- A user can select a profile, start a dry run, inspect phase state, and open artifact paths from
  the TUI.

---

## 9. Acceptance and Verification

<!-- MEMINIT_SECTION: acceptance -->

Every milestone must finish with:

```bash
./scripts/dev-check
meminit check --format json
git diff --check
```

Distribution-specific verification:

```bash
./scripts/install-dev
./.venv/bin/code-review-loop --dry-run --quiet-progress --summary-format json
./.venv/bin/revrem --dry-run --quiet-progress --summary-format json

./scripts/promote-stable
cd ../Meminit
code-review-loop --dry-run --quiet-progress --summary-format json
revrem --dry-run --quiet-progress --summary-format json
```

Profile-specific verification, once implemented:

```bash
revrem config doctor
revrem config show final-pr
revrem --profile final-pr --dry-run --summary-format both
```

Run-history verification:

```bash
revrem history list
revrem history --format json list --limit 5
```

---

## 10. Alternatives Considered

<!-- MEMINIT_SECTION: alternatives -->

- **Keep one editable install on PATH:** rejected because every repo would immediately consume
  in-progress code from this checkout.
- **Copy the script into each repo:** rejected because fixes and tests drift across repositories.
- **Use `pipx install -e .` for both dev and stable:** rejected because it blurs the promotion
  boundary; editable installs are appropriate for this repo only.
- **Local web UI:** deferred because it introduces a Node/browser runtime and a second process for a
  solo-operator tool.
- **Skill-only implementation:** rejected because executable loop behavior belongs in tested Python
  code, with skills acting as operator guidance.

---

## 11. Resolved Decisions and Open Questions

<!-- MEMINIT_SECTION: open_questions -->

### Resolved Decisions

- `revrem` is the human-facing alias; `code-review-loop` remains stable for scripts and agents.
- Stable local install lives under `~/.local/share/revrem/` with launchers in `~/.local/bin`.
- User config uses `~/.config/revrem/`; run history uses `~/.local/share/revrem/`.
- WSL2/Linux is the primary target.
- Rich and Textual remain optional extras.
- TOML writes use a small purpose-built renderer for the limited profile schema
  instead of adding a default runtime dependency.
- Harness names are validated through an early registry and command-planning
  adapter boundary; only the Codex adapter is executable today.
- Run history is append-only JSONL to avoid read-modify-write corruption and to
  keep TUI recent-run views simple.

### Open Questions

- Which non-Codex headless harness should be implemented first, and what exact
  machine-readable review/remediation contract should its adapter expose.
- Whether the full Textual Run Monitor should execute the existing CLI in a
  subprocess for maximal isolation or call the loop core directly with an event
  stream adapter.

---

## 12. Version History

<!-- MEMINIT_SECTION: version_history -->

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.7 | 2026-05-02 | Codex | Added reusable harness command-planning boundary and TUI profile command previews for future interactive screens |
| 0.6 | 2026-05-02 | Codex | Hardened Rich progress styling expectations, corrected conservative no-op unknown close-down semantics, and added a dependency-guarded TUI launch smoke-test requirement |
| 0.5 | 2026-05-02 | Codex | Added optional verified commit-after-remediation phase, Conventional Commit subject policy, phase-specific effort overrides, no-op remediation close-down, and first dependency-gated TUI entry slice |
| 0.4 | 2026-05-02 | Codex | Implemented FR-9 run history; added history CLI, JSONL architecture contract, optional read-only Codex triage, local progress timestamps, and initial optional Rich progress |
| 0.3 | 2026-05-02 | Codex | Marked profile/config milestones implemented; clarified remaining run-history, Rich progress, and TUI scope |
| 0.2 | 2026-05-01 | Codex | Reworked PRD into staged engineering contract; added dev/stable distribution boundary, architecture constraints, milestones, and acceptance gates |
| 0.1 | 2026-05-01 | GitCmurf | Initial draft |
