---
document_id: REVREM-TASK-002
type: TASK
title: Next-phase post-launch implementation tasks
status: Draft
version: '0.4'
last_updated: '2026-05-13'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: PR-sized implementation programme for the post-launch foundation phase of REVREM-PLAN-003, with shared contracts, traceability, and modern engineering best practices baked in.
keywords:
- revrem
- roadmap
- hardening
- devex
- diagnostics
- distribution
- schema
- events
- suppressions
- harness
- best-practices
- traceability
related_ids:
- REVREM-PLAN-003
- REVREM-PLAN-002
- REVREM-PRD-001
- REVREM-DEVEX-001
- REVREM-TEST-001
- REVREM-TASK-001
- REVREM-ADR-003
- REVREM-ADR-004
- REVREM-ADR-005
- REVREM-ADR-006
---

# TASK: Next-phase post-launch implementation tasks

## How To Read This Document

This is an engineering handover. It assumes the reader is the orchestrator of
agentic coding sessions or a human reviewer assigning work. It is not a
narrative roadmap — for that, read `REVREM-PLAN-003`.

Read in this order:

1. **Context, Phase Goal, Non-Goals** — what this phase is and is not.
2. **Glossary** — fix vocabulary before anything else; many later
   sections refer back here.
3. **Shared Contracts Registry** — the cross-cutting agreements (fingerprint
   algorithm, schema versioning, exit codes, JSON conventions, write
   semantics) that every F-task must obey. **This is the most important
   section in the document.** Do not skip it.
4. **Phase Dependency Graph** + **Traceability Matrix** — what depends on what,
   and how each task ladders up to the plan's milestones and success metrics.
5. **Code / Tests / Docs Alignment Contract** — the anti-drift rules that
   keep implementation, verification, and documentation moving together.
6. **Global Engineering Rules** + **Modern Best-Practice Checklist** — the
   per-PR rules. Cited from each task; read once.
7. **Tasks F0–F10** — PR-sized work packages.
8. **Phase Exit Criteria & ADR Closure** — how we know the phase is done.

If a task and the contracts registry disagree, the **registry wins**. Open a
PR amending the registry rather than diverging silently.

## Context

`REVREM-PLAN-003` sets the post-launch roadmap for turning RevRem from a
usable MVP into a hardened local-first review-remediation utility. This task
document converts the **post-launch foundation phase** of that roadmap (plan
milestones M0–M4, plus the M6 fake-harness slice) into PR-sized work packages
that an agentic coding orchestrator can execute, test, review, and mark done
without relying on unstated project memory.

The phase's purpose is to make RevRem externally installable, predictable in
failure, schema-backed, safe to run repeatedly, and ready for later TUI, CI,
archive, and multi-harness work. It intentionally stops before the most
visible autonomy surfaces because those surfaces must consume stable
contracts rather than invent their own.

The current codebase already has useful seams:

- `src/code_review_loop/cli.py` owns the loop, command parsing, phase
  execution, progress output, summaries, checks, commit handling, and the
  current preflight helpers. It is large (~2.8k lines) and most new
  cross-cutting logic in this phase should land in **new focused modules**
  rather than further inflate `cli.py`.
- `src/code_review_loop/harnesses.py` owns the Codex harness registry and the
  reserved backend names.
- `src/code_review_loop/profiles.py` owns profile parsing, validation, profile
  import/export, and config write paths.
- `src/code_review_loop/progress.py` owns Rich/compact terminal rendering.
- `src/code_review_loop/run_history.py` owns append-only user-level history.
- `src/code_review_loop/tui.py` and `src/code_review_loop/tui_state.py` are
  currently a control panel and artifact viewer, not a second execution
  engine. **They must remain so for this phase.**

This task list assumes `REVREM-TASK-001` is complete enough that the public
repository baseline exists and CI is green on `main`.

## Phase Goal

Deliver a sequence of small, reviewable PRs that establishes RevRem's stable
foundation for 0.5/0.6-era work:

- public distribution can be smoke-tested without cloning the repository;
- setup failures are caught before model invocation;
- every failed run leaves machine-readable diagnostics;
- artifact schemas are versioned, JSON-Schema-validated, and tested against
  fixtures;
- a single fingerprint algorithm is shared by diagnostics, triage,
  suppressions, and bug bundles;
- triage output has a stable contract;
- suppressions make repeated runs tolerable and auditable;
- execution progress is represented as an event stream that all renderers
  consume;
- cost, wall-clock, cancellation, and replay behavior are testable without
  calling a real model;
- the first non-Codex work is a **fake** harness contract, not a real vendor
  adapter.

## Non-Goals For This Phase

Do **not** implement these in this task series:

- TUI-launched real runs.
- Git hooks or `revrem install-hooks`.
- GitHub Action / PR comment integration.
- Static HTML report (`revrem report`).
- Background daemon / `revrem watch`.
- Archive export / dataset export.
- Real Claude, Gemini, opencode, Kilo, OpenRouter, or generic HTTP backend.
- Hosted service, telemetry, IDE extension, or web UI.
- Plugin entry points (`revrem.harnesses`, `revrem.checks`, `revrem.renderers`).

Those become eligible only after the phase exit criteria are satisfied. PRs
that quietly add any of them must be split or rejected.

## Final Review Corrections Applied

This section records the critical review decisions that prevent the task list
from becoming an impressive but brittle implementation script.

- **No platform-dependent fingerprints.** Finding fingerprints use the path
  spelling recorded by Git after POSIX normalization. They do not lowercase
  paths based on the executing filesystem because that would make Linux and
  macOS produce different fingerprints for the same repository.
- **No accidental unbounded-timeout regression.** Existing RevRem behavior
  allows explicit zero timeout values to disable a phase timeout. F3 may warn
  when this weakens bounded execution, but it must not silently reclassify the
  existing explicit behavior as invalid.
- **No raw audit-log leakage by default.** Suppression audit logs can contain
  emails, issue references, and rationale text. Bug bundles include a
  redacted audit summary by default; raw audit logs require the same explicit
  raw-transcript opt-in path as model transcripts.
- **No changelog discipline without a changelog.** F0 must verify or create
  `CHANGELOG.md` before the global rule requiring changelog updates becomes
  enforceable.
- **No schema work without a documented namespace.** F4 must create the
  `docs/52-api/` schema area and document that JSON schema files there are
  machine-readable reference artifacts, not Meminit-governed Markdown docs.
- **No fake precision metric.** Triage precision in F6 is measured against a
  labelled fixture corpus and deterministic parser/contract outputs. It is not
  presented as proof of live model quality until live evaluation exists.
- **No new release workflow secret debt.** F2 uses PyPI Trusted Publishing
  where possible; any fallback to long-lived tokens must be documented as a
  temporary risk with removal criteria.

## Glossary

Fix vocabulary before scoping. Every F-task uses these terms with this
meaning.

| Term | Definition |
|---|---|
| **run** | A single invocation of `revrem` that produces an artifact directory under `.revrem/runs/<run_id>/`. |
| **run_id** | Timestamp + short random suffix (`YYYYMMDDTHHMMSSZ-xxxx`). Stable per run; appears in every artifact and event. |
| **harness** | An adapter that drives review/remediation/triage commands against a model backend. Codex is the reference harness; `fake` is the test harness (F10). |
| **phase** | A bounded operation inside the loop: `preflight`, `review`, `triage`, `remediate`, `check`, `commit`, `summary`. |
| **finding** | A single reviewer-reported issue. Carries a normalized `rule_id` (when extractable), free-text summary, affected file/range, severity. |
| **fingerprint** | Stable hash identifying a finding across runs (see Contracts Registry §3). The same fingerprint is used by diagnostics, triage, suppressions, and bug bundles. |
| **artifact** | A file written under the run directory. Public artifacts (`summary.json`, `diagnostics.json`, `triage.json`, `events.jsonl`) are schema-versioned. |
| **event** | A single structured record on the loop's event stream (F8). Append-only, JSONL, monotonically sequenced per run. |
| **schema_version** | Integer-major + integer-minor version of a public JSON contract. Additive minor bumps; breaking changes require major bump and migration note. |
| **suppression** | An auditable, fingerprint-keyed dismissal of a finding (F7). |
| **budget / ceiling** | A pre-declared upper bound on tokens, USD cost, or wall-clock seconds (F9). |
| **profile** | A reusable named configuration of CLI arguments stored in `.revrem.toml` or user config. |
| **reference repo** | The fixture Python repository under `tests/fixtures/reference-repo/` used to measure baseline metrics from the plan. Created in F0. |

## Shared Contracts Registry

Eight cross-cutting contracts. Each is owned by exactly one F-task that
introduces it; later tasks consume without redefining. Treat this section as
load-bearing — drift here causes silent bugs across modules.

### 1. Schema Versioning (owned by F4)

- Every public JSON artifact carries `"schema_version": "<major>.<minor>"`
  at the top level.
- **Additive** changes (new optional fields) bump minor.
- **Breaking** changes (field removal, rename, type change, semantic change)
  bump major and require a migration note in the PR body and `CHANGELOG.md`.
- A CI test (`tests/test_artifact_schema.py::test_no_unintentional_breaks`)
  diffs each schema against its previous version on disk once a previous
  version exists, and fails on a detected break without an accompanying major
  bump.
- JSON Schema files live under `docs/52-api/schemas/<name>-vN.schema.json`
  using **JSON Schema draft 2020-12**, with stable `$id` of form
  `https://github.com/GitCmurf/revrem/schemas/<name>/v<major>` (the URL need
  not resolve; it is an identifier, not a fetch target).
- Each artifact also records `cli_version`, `harness`, `harness_version`
  (when reportable), `profile`, and `command_line`.

### 2. Canonical JSON Serialization (owned by F4)

- UTF-8, NFC-normalized strings.
- `sort_keys=True`, `ensure_ascii=False`, `indent=2` for human-readable
  artifacts; `indent=None` (single line) for `events.jsonl`.
- LF line endings; final newline; no BOM.
- Numbers: integers as integers, floats as floats; **money uses `Decimal`
  serialized as a JSON string** (e.g., `"usd": "0.0345"`) to avoid float
  drift.
- Times: ISO-8601 UTC with `Z` suffix and millisecond precision
  (`2026-05-09T12:08:23.451Z`).

### 3. Finding Fingerprint (owned by F4, used by F5/F6/F7/F8)

A single algorithm. Defined once, imported everywhere.

```python
def fingerprint(finding) -> str:
    """SHA-256 over a canonical, rename-tolerant tuple."""
    components = [
        finding.normalized_rule_id or "<none>",          # e.g. "B608" or "<none>"
        finding.normalized_path,                         # repo-relative POSIX path as recorded by Git
        finding.normalized_message_stem,                 # message lower-cased, whitespace-collapsed, first 160 chars
        finding.severity_bucket,                         # info|low|medium|high|critical
    ]
    blob = "\x1f".join(components).encode("utf-8")
    return "f1:" + hashlib.sha256(blob).hexdigest()[:16]
```

- Prefix `f1:` declares the fingerprint algorithm version. A change to the
  algorithm requires `f2:` and a migration story for existing suppressions.
- The fingerprint is intentionally rename-fragile (path is part of the
  hash); suppressions are expected to expire when files move. This is
  documented behavior, not a bug.
- Severity is intentionally part of the hash so an escalated finding does not
  silently inherit a lower-severity suppression.
- Implementation lives in `src/code_review_loop/fingerprints.py` and is
  unit-tested with golden vectors in `tests/test_fingerprints.py`.

### 4. Atomic Write & Path Safety (owned by F4)

- All JSON artifacts use a write-temp-then-`os.replace` pattern.
- Artifact paths are validated to live within the run directory: no `..`
  components, no symlinks resolving outside the run dir.
- Run directory creation uses `os.makedirs(..., exist_ok=False)` to detect
  collisions; collisions retry with a fresh `run_id` suffix.

### 5. Stable Exit Codes (owned by F3, ratified phase-wide)

| Code | Meaning | Owning task |
|---:|---|---|
| 0 | Clear / success | (existing) |
| 1 | Unexpected error (uncaught exception, internal bug) | (existing) |
| 2 | Findings or check failures remain after bounded loop | (existing) |
| 3 | Budget ceiling hit (tokens / USD / wall-clock) | F9 |
| 4 | Blocking setup failure (preflight blocked) | F3 |
| 5 | Cancelled by operator (Ctrl-C drained cleanly) | F9 |
| 6 | Doctor warnings, with `--strict` | F3 |

Codes are documented in `--help` and in the README. Tests in F3/F9 assert
each code is reachable.

### 6. Event Envelope (owned by F8)

```jsonc
{
  "schema_version": "1.0",
  "run_id": "20260509T120823Z-a1b2",
  "seq": 17,                 // monotonic, gap-free, per run
  "ts": "2026-05-09T12:08:24.103Z",
  "kind": "phase_result",
  "phase": "review",
  "iteration": 1,
  "payload": { /* kind-specific */ }
}
```

- `events.jsonl` is **append-only**, one JSON object per LF-terminated line.
- `seq` is monotonic and gap-free per run; a missing `seq` is a corruption
  signal.
- `ts` is for display and audit; ordering is by `seq`, never by `ts`.
- Sinks must be **non-blocking**: a slow renderer cannot stall the loop.
  The JSONL sink uses buffered writes flushed at phase boundaries plus on
  failure paths.

### 7. Redaction Defaults (owned by F5)

- On by default. When the optional `[redaction]` extra is installed,
  `detect-secrets` drives secret detection. A built-in fallback regex set
  covers the case where the extra is not installed.
- Always redacts: API key patterns, `Authorization:` headers, private key
  blocks, `.env` assignments, `$HOME` and `$USER` strings.
- Replacement token `[REDACTED:<category>]` (e.g. `[REDACTED:env-var]`).
- Redaction is **idempotent**: redacting an already-redacted blob produces
  byte-identical output.

### 8. Logging vs Events (owned by F8)

- **Events** (`events.jsonl`) are the contract. Consumed by replay, TUI,
  reports.
- **Logs** are operator-facing terminal/file output. Use Python `logging`
  with a single root configuration, levels per RFC 5424 (`DEBUG`/`INFO`/
  `WARNING`/`ERROR`/`CRITICAL`), and structured `extra={"run_id": ...}`.
  Logs are **not** a contract; tests must not parse them.

## Phase Dependency Graph

```text
F0 baseline
  ├─> F1 package identity + release checks
  │     └─> F2 public install smoke + rollback runbook
  ├─> F3 diagnostics model + revrem doctor
  │     ├─> F4 artifact schema v1 + fingerprint + fixtures
  │     │     ├─> F5 bug-report bundle + redaction
  │     │     ├─> F6 triage contract + remediation handoff
  │     │     │     └─> F7 suppression file + suppress CLI
  │     │     ├─> F8 event sink + events.jsonl + replay  (soft-blocked by F6,F7)
  │     │     │     └─> F9 budgets + cancellation + resume
  │     │     └─> F10 fake harness contract  (soft-blocked by F8)
  │     └─> docs/test ledgers updated continuously
```

Parallelism rules:

- F1 and F3 may start in parallel after F0.
- F4 may start once F3 has defined the diagnostic data model.
- F5 may start once F4 has the fingerprint and writer helper.
- F6 may start once F4 has the schema conventions (even before F5 finishes).
- F7 hard-depends on F4 and F6.
- F8 hard-depends on F4. If it lands before F7, the `suppressed` event kind
  is reserved-but-unemitted; F7 wires it.
- F9 hard-depends on F8 (cost/cancellation events live on the event stream).
- F10 hard-depends on F3 (capability surface) and soft-depends on F8 (the
  fake harness gains greatly from emitting recorded event fixtures).

## Traceability Matrix

Every F-task ladders up to a plan milestone, contributes to plan success
metrics, and unlocks an autonomy level. PRs that touch a task must update
this matrix if scope shifts.

| Task | Plan milestone | Plan success metric(s) advanced | Unlocks autonomy level | Freezes contract |
|---|---|---|---|---|
| F0 | M0 | (baseline) | — | — |
| F1 | M1 | Time-to-first-run | L1 | Package identity |
| F2 | M1 | Time-to-first-run; rollback safety | L1 | Release flow |
| F3 | M2 | Doctor coverage ≥95%; MTTAD <60 s | L1 | Diagnostic model + exit codes |
| F4 | M2 | MTTAD; CI replay coverage prerequisite | L1 | Artifact schema v1; fingerprint |
| F5 | M2 | MTTAD; bug-report quality | L1 | Redaction defaults |
| F6 | M3 | Triage precision ≥0.85 | L2 | Triage contract |
| F7 | M3 | Repeated-run tolerability | L2 | Suppression contract |
| F8 | M4 | Replay coverage 100%; event-driven UIs | L2 | Event envelope v1 |
| F9 | M4 | Cost-cap respected 100% | L2/L3 | Budget + cancellation + exit codes 3/5 |
| F10 | M6 (slice) | Harness portability prerequisite | (gates L3) | Harness capability surface |

## Code / Tests / Docs Alignment Contract

Every PR in this phase must leave three surfaces in agreement: runtime
behavior, tests, and documentation. This table makes that explicit so an
agentic coding orchestrator has no discretion to ship code-only or docs-only
drift.

| Change type | Code surface | Required tests | Required docs |
|---|---|---|---|
| New CLI command or flag | `cli.py` parser plus focused module where behavior lives | Parser test, behavior test, exit-code test where applicable | README or `REVREM-DEVEX-001`, `--help`, CHANGELOG |
| New profile key | `profiles.py` dataclass, parser, serializer, validation | Parse/merge/reject tests in `tests/test_profiles.py` | Profile examples in `REVREM-DEVEX-001`, schema notes if public |
| New JSON artifact field | Artifact writer/model/schema | Fixture validation and backwards-compat test | `docs/52-api/` schema docs, CHANGELOG if public |
| New diagnostic code | `diagnostics.py` registry | JSON schema test, text rendering test, live preflight integration test | Generated diagnostics table, README troubleshooting if user-facing |
| New event kind | `events.py` envelope + schema | Golden fixture, replay test, renderer test where visible | Event schema docs and `REVREM-PLAN-002` if it affects TUI readiness |
| New suppression behavior | `suppressions.py` and loop integration | Match/no-match, expiry, critical override, audit-log tests | Suppression workflow docs and ADR |
| New harness capability | `harness_contract.py` and adapters | Fake harness contract test, reserved-real-harness rejection test | Harness capability table and ADR |
| New packaging/release behavior | `pyproject.toml` / workflow | Build, install smoke, metadata test | README install, release runbook, CHANGELOG |

Alignment rules:

- A behavior is not "done" until its CLI help, public docs, and tests use the
  same names, exit codes, and defaults.
- Golden fixtures are reviewed as public contract changes, not incidental test
  data.
- Generated docs must be regenerated by a checked-in script; hand-edited
  generated tables are not accepted.
- If a PR deliberately leaves a doc or test gap, it must add a follow-up task
  and explain why the gap is safe before merge.

## Global Engineering Rules

Every PR in this task series must obey these. They are referenced — not
re-stated — by each F-task.

- **Atomic unit of work** = code + tests + docs (governed where applicable).
- **Single execution owner.** `run_loop()` (or its extracted successor)
  remains the only execution owner. TUI, reports, history, replay, and CI
  surfaces consume events and artifacts.
- **No model output executed as shell.** Shell execution remains behind
  operator-authored check commands or explicit harness commands.
- **Bounded by default.** New model-invoking paths must expose iteration,
  timeout, and cost guardrails before they are defaultable.
- **Module discipline.** Prefer typed dataclasses or small pure functions
  at boundaries. Do not enlarge `cli.py` when a focused module fits.
  New modules are < 600 lines unless justified in the PR body.
- **Schema discipline.** Public JSON artifacts include `schema_version`.
  Public schema changes are JSON-Schema-validated against fixtures and
  documented under `docs/52-api/schemas/`.
- **Dependency discipline.** No new runtime dependency unless it removes
  clear operational risk or sits behind an optional extra.
- **DocOps discipline.** Never modify a `document_id`. Use `meminit new`
  for new governed docs. Update `related_ids` reciprocally.
- **Conventional Commits.** Commit subjects follow
  `<type>(<scope>): <summary>` per Conventional Commits 1.0; `type` ∈
  `feat|fix|docs|chore|refactor|test|build|ci|perf|revert`.
- **CHANGELOG.** After F0 creates or verifies `CHANGELOG.md`, every
  user-visible change updates it under `## [Unreleased]` using
  Keep-a-Changelog sections.
- **ADRs.** Tasks marked "Freezes contract" in the traceability matrix
  produce an ADR (`meminit new ADR <Title>`) recording the decision and
  alternatives considered. The ADR is part of the same PR.

## Modern Best-Practice Checklist (Per PR)

Reviewers verify each box. Cite this list in the PR description.

- [ ] **Typing.** New public functions carry full annotations. New modules
  pass either `mypy --strict` directly or the project-documented strictness
  gate introduced with that module.
- [ ] **Lint.** `ruff check` passes with the project ruleset. New modules
  opt into security linting where practical; if the repo has not enabled
  bandit-style `S` rules yet, the PR records the evaluated risk and deferral.
- [ ] **Coverage.** New modules ≥ 90% line + branch coverage; core safety
  modules (`fingerprints`, `redaction`, `budgets`, `events`) ≥ 95%.
- [ ] **Property tests.** Where invariants exist (fingerprint stability,
  JSON round-trip, redaction idempotence, event seq monotonicity),
  consider Hypothesis-style property tests.
- [ ] **Determinism.** New tests are stable across run order and OS;
  no time/wall-clock dependencies; randomness seeded.
- [ ] **Security.** Subprocess invocations use list-form args (no
  `shell=True`). Path inputs validated for traversal. Secrets never
  logged.
- [ ] **Privacy.** No user content escapes the run directory by default.
  Anything optional must be flag-gated and documented.
- [ ] **A11y / UX.** Terminal output remains readable without color; no
  ANSI escapes when stdout is not a TTY; locale-independent.
- [ ] **i18n posture.** No locale-dependent string parsing; UTC-only times.
- [ ] **Reproducibility.** Build artifacts are reproducible
  (`SOURCE_DATE_EPOCH` honored); pinned tool versions in CI matrix.
- [ ] **Backward compatibility.** Schema changes additive within major;
  CLI flag changes additive; deprecations carry a release before removal.
- [ ] **AI-generated code.** Autogenerated drafts have been reviewed for
  architectural alignment, real APIs, security-sensitive edge cases, and
  unnecessary rule or vocabulary sprawl.
- [ ] **Docs.** README, governed docs, and `--help` all updated where
  user-visible behavior changes. ADR added if a contract is frozen.

## Required Verification For Every PR

Minimum local gate:

```bash
./scripts/dev-check
git diff --check
meminit check --format json
```

Additional, area-scoped gates:

| Touches | Gate |
|---|---|
| Packaging | `python -m build --sdist --wheel`; `python -m twine check dist/*`; fresh-venv install smoke |
| Profiles | `./.venv/bin/pytest -q tests/test_profiles.py tests/test_cli.py` |
| Harnesses | `./.venv/bin/pytest -q tests/test_harnesses.py tests/test_cli.py` |
| TUI / TUI state | `./.venv/bin/pytest -q tests/test_tui.py tests/test_tui_state.py` |
| Schemas | `./.venv/bin/pytest -q tests/test_artifact_schema.py` (introduced in F4) |
| Events / replay | `./.venv/bin/pytest -q tests/test_events.py tests/test_replay.py` (introduced in F8) |
| Redaction | `./.venv/bin/pytest -q tests/test_redaction.py` (introduced in F5) |
| Budgets / resume | `./.venv/bin/pytest -q tests/test_budgets.py` (introduced in F9) |

The PR body must paste exact command outcomes, including failures fixed
before final review (a successful CI run on the final commit is *not*
sufficient — reviewers want the iteration story).

CI matrix (target): Python 3.11 and 3.12 on Linux + macOS for unit tests;
3.12 on Linux for packaging smoke. Python 3.13 added under
`continue-on-error` to surface forward-compat issues without gating.

## Orchestrator Handoff Format

For each PR, the orchestrator produces:

- branch name (Conventional Commits-style: `feat/...`, `chore/...`);
- implemented task IDs (e.g., `F4`, partial `F5`);
- changed files grouped by module;
- migration notes if schemas, exit codes, or config shapes changed;
- ADR ID(s) introduced or updated;
- CHANGELOG section preview;
- verification commands and outputs;
- known deferrals;
- screenshots or terminal excerpts only when they prove operator-visible
  behavior;
- best-practice checklist with each box explicitly ticked or justified.

Each PR must be reviewable independently. If a task cannot be finished
without broadening scope, **split** it rather than silently absorbing the
next task.

---

## Task List

### F0. Establish The Phase Baseline

**Branch:** `chore/foundation-phase-baseline`

**Plan link:** M0. **Unlocks:** prerequisite for F1–F10.

**Purpose:** confirm the post-launch repository state and stand up the
fixture infrastructure later tasks depend on.

**Blocked by:** `REVREM-TASK-001` public baseline substantially complete.

**Primary write set:**

- `docs/05-planning/tasks/task-002-next-phase-post-launch-implementation-tasks.md` (this file)
- `tests/fixtures/reference-repo/` (new — minimal Python repo with seeded issues for benchmarks)
- `docs/55-testing/test-001-utility-verification-strategy.md` (extend with phase entry checklist)
- `CHANGELOG.md` (create if absent; Keep a Changelog format)
- optional GitHub issue labels / project metadata outside this repo

**Actions:**

1. Confirm `main` is the default branch on GitHub and local `main` matches
   `origin/main`.
2. Confirm no obsolete launch branches are targeted by open automation PRs.
3. Run the full local gate (including `meminit check --format json`) and
   record output in the PR body.
4. Create GitHub issues / orchestrator tickets for F1–F10. Apply labels:
   `foundation`, `trust`, `diagnostics`, `schema`, `triage`, `events`,
   `harness`, `budgets`.
5. **Stand up the reference fixture repo** under
   `tests/fixtures/reference-repo/` containing 6–10 deliberately-flawed
   Python files spanning the issue classes the bundled profiles will
   eventually showcase (security, performance, refactor, docs). Seed it
   with at least: a SQL injection, a quadratic-in-loop bug, a missing
   docstring, a duplicated helper, an unused import, a broad `except`.
6. Add `tests/fixtures/reference-repo/EXPECTED_FINDINGS.md` listing each
   seeded issue with class, file, line, and expected severity.
7. Document the phase entry checklist in the testing strategy doc.
8. Create or verify `CHANGELOG.md` with a `## [Unreleased]` section before
   downstream PRs are required to update it.

**Tests:** none new beyond fixture presence assertion
(`tests/test_fixtures.py::test_reference_repo_present`).

**Docs:** this task file + testing strategy update.

**Done when:**

- The phase task list is committed at v0.2 or later.
- The local gate is green; output pasted in PR body.
- Reference fixture repo exists and is referenced by F3/F4/F6 plans.
- `CHANGELOG.md` exists and the global changelog rule is enforceable.
- Each downstream task has a tracking issue or orchestrator entry.
- No implementation feature has been mixed into the baseline PR.

**Risks:** scope creep into "useful" baseline fixes — split anything else
into its own PR.

---

### F1. Package Identity, Metadata, And Release Checks

**Branch:** `feat/package-release-foundation`

**Plan link:** M1. **Unlocks:** L1 (profile-driven external use).
**Freezes contract:** package identity (ADR required).

**Purpose:** make package metadata release-grade *before* public install
docs claim PyPI or `pipx` support.

**Blocked by:** F0.

**Primary write set:**

- `pyproject.toml`
- `src/code_review_loop/__init__.py`
- `.github/workflows/release.yml`
- `.github/workflows/ci.yml` (matrix expansion)
- `tests/test_packaging.py`
- `README.md` (conservative claims only)
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/45-adr/adr-NNN-package-identity.md` (new ADR via meminit)
- governed release runbook (`docs/60-runbooks/runbook-NNN-revrem-release.md`)
  if not already present

**Implementation requirements:**

1. **Identity decision (ADR-tracked).**
   - Preferred: publish as `revrem` if available on PyPI/TestPyPI.
   - Fallback: keep `code-review-loop` as the dist name and document
     `revrem` as the console script alias.
   - The ADR records which option was chosen and why.
2. **Metadata.** Ensure `pyproject.toml` declares:
   - accurate one-line description;
   - project URLs (`Homepage`, `Source`, `Issues`, `Changelog`);
   - PyPI classifiers matching the CI Python matrix;
   - SPDX license expression (`Apache-2.0`);
   - keywords;
   - README as long description with explicit content type;
   - extras: `[progress]`, `[tui]`, `[redaction]`, `[dev]`. Each extra
     declares only what real code requires.
3. **Console script.** `[project.scripts]` exposes both `revrem` and
   `code-review-loop` until the deprecation policy retires the legacy
   name (not in this phase).
4. **Version single-sourcing.** `__init__.py:__version__` is the single
   source of truth; `pyproject.toml` reads via dynamic versioning or a
   build-time test asserts equality.
5. **CI release-check job.** Builds sdist + wheel, runs
   `python -m twine check`, verifies `revrem --version` from the built
   wheel in a clean venv.
6. **Reproducible builds.** Honour `SOURCE_DATE_EPOCH`; pin build-system
   versions in `pyproject.toml`'s `[build-system]` requires.
7. **Tag/version consistency.** Release workflow refuses a tag that does
   not match `__version__`.

**Tests (new/updated in `tests/test_packaging.py`):**

- `test_version_matches_init`
- `test_console_script_entry_points_present`
- `test_long_description_renders`
- `test_classifiers_match_ci_matrix`
- `test_extras_install_minimal_set`
- `test_readme_does_not_overclaim_pypi` (string-match guard)

**Docs:**

- Distinguish *contributor source install* (`./scripts/install-dev`) from
  *user package install* (deferred to F2 README update).
- High-level rollback guidance: yank bad PyPI release, mark GitHub
  release superseded, pin prior version. Detailed runbook in F2.

**Migration notes:** if the dist name changes, document the migration
path for existing `pip install -e .` users in the ADR.

**Done when:**

- `python -m build --sdist --wheel` and `python -m twine check dist/*`
  pass locally and in CI.
- `./scripts/dev-check` passes.
- README install claims remain conservative pending F2.
- Release workflow has a concrete version-mismatch failure path.
- ADR landed.

**Risks:** PyPI naming unavailable → fallback path documented in ADR;
no work blocked.

---

### F2. Public Install Smoke And Rollback-Proof Release Flow

**Branch:** `feat/public-install-smoke`

**Plan link:** M1. **Unlocks:** L1. **Freezes contract:** release flow
(ADR required).

**Purpose:** prove a fresh user can install and run RevRem without
cloning the repository, with provenance and a clean rollback path.

**Blocked by:** F1.

**Primary write set:**

- `.github/workflows/release.yml`
- `.github/workflows/ci.yml`
- `tests/test_packaging.py`
- `README.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/60-runbooks/runbook-NNN-revrem-release.md`
- `docs/45-adr/adr-NNN-release-trust.md`

**Implementation requirements:**

1. **Fresh-environment install smoke in CI.** Matrix: Linux + macOS,
   Python 3.11/3.12. Each cell:
   - create a clean venv (or use `pipx`);
   - install the built wheel from the local `dist/`;
   - run `revrem --version`;
   - run `revrem --help`;
   - run `revrem doctor --format json` against
     `tests/fixtures/reference-repo/`.
2. **TestPyPI publish on RC tags** (`v*-rc*`) using PyPI's **Trusted
   Publisher (OIDC)** flow — no long-lived API tokens in repo secrets.
3. **PyPI publish on signed release tags** (`v*` without `-rc`) via the
   same OIDC publisher.
4. **Provenance.** Use
   `actions/attest-build-provenance` to attest sdist + wheel; attach
   SHA-256 checksums and **Sigstore** signatures to the GitHub Release.
5. **Dry-run capability.** Workflow runnable with `workflow_dispatch`
   in dry-run mode without any publishing credentials, producing
   artifacts for inspection.
6. **README install section** updated only after the publish path is
   verified end-to-end. Add `pipx`, `pip`, and `uv tool install`
   commands.
7. **Rollback runbook.** Step-by-step: (a) `pip` yank the bad version,
   (b) edit GitHub Release to "superseded by", (c) cut a hotfix tag
   bumping patch and republish, (d) write a CHANGELOG note. Include
   decision criteria: when to yank vs document workaround.

**Tests:**

- CI smoke uses the *built artifact*, not editable install.
- `test_revrem_version_matches_pkg_metadata` runs against the installed
  wheel.
- A workflow-lint test (e.g., `actionlint`) gates `.yml` syntax.

**Docs:**

- Exact install commands.
- Verification commands users can run to check provenance / signature.
- Rollback runbook, ADR.

**Done when:**

- A CI job proves fresh install from the built artifact on at least
  Linux + macOS, Python 3.12.
- README install instructions match the verified path.
- Release workflow runs as dry-run without secrets.
- Provenance attestation + Sigstore signature attached to a test release.
- Rollback runbook references real commands, not abstractions.

**Risks:** OIDC trust policy misconfiguration → dry-run on TestPyPI
catches before PyPI.

---

### F3. Diagnostic Result Model And `revrem doctor`

**Branch:** `feat/doctor-diagnostics`

**Plan link:** M2. **Unlocks:** L1. **Freezes contract:** diagnostic
model + exit codes (ADR required).

**Purpose:** catch common failures before launching Codex and provide
stable, machine-readable diagnostics that downstream surfaces consume.

**Blocked by:** F0. Runs in parallel with F1.

**Primary write set:**

- `src/code_review_loop/diagnostics.py` (new)
- `src/code_review_loop/cli.py`
- `tests/test_cli.py`
- `tests/test_diagnostics.py` (new)
- `tests/fixtures/diagnostics/` (new)
- `docs/52-api/schemas/diagnostics-v1.schema.json` (new)
- `docs/45-adr/adr-NNN-diagnostic-model-and-exit-codes.md` (new)
- `README.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/55-testing/test-001-utility-verification-strategy.md`

**Implementation requirements:**

1. **`DiagnosticIssue` dataclass.** Fields:
   - `code` — stable string id (e.g., `revrem.preflight.invalid_base`);
   - `severity` — `ok` / `warn` / `blocking`;
   - `message` — human-readable, complete sentence;
   - `hint` — recommended fix, complete sentence;
   - `evidence` — structured payload (paths, command, exit codes);
   - `fingerprint` — uses the F4 algorithm where finding-shaped, else
     a code-derived stable hash.
   - `schema_version`.
2. **`revrem doctor`** (alias `revrem preflight`) implements the
   ratified preflight set:
   - git repository exists;
   - `--base` exists and resolves;
   - `HEAD` and base share a merge base;
   - dirty worktree blocks commit mode;
   - artifact directory creatable and writable (and not on a read-only
     mount);
   - configured harness executable on PATH and runnable via the
     adapter-defined health check (Codex currently uses `--version`);
   - configured check commands resolvable;
   - timeout values valid: negative values are blocking errors; explicit
     zero values are accepted only where the existing CLI defines them as
     "disable timeout" and produce a warning unless paired with a documented
     bounded alternative;
   - profile names resolve to a config file;
   - reserved-but-unimplemented harnesses are rejected for live
     execution;
   - locale/encoding sane (UTF-8 capable filesystem; warn on POSIX-C
     locale where it would break artifact text).
3. **Output.**
   - `--format text` (default when stdout is a TTY): human, color when
     supported, plain otherwise.
   - `--format json` (default when stdout is not a TTY) — JSON Schema
     `diagnostics-v1`. Stable ordering by (severity, code).
   - `--strict` upgrades warnings to non-zero exit (code 6).
4. **Live execution integration.** `run_loop` invokes the same preflight
   code path before the first model invocation. There is **one**
   diagnostic implementation; tests assert no parallel logic exists.
5. **No model calls during doctor checks.** Hard rule, asserted by a
   test that monkeypatches `default_runner` to fail on any
   harness-shaped invocation.
6. **Exit codes** per the contract registry (§5).

**Tests:**

- Fixture worktrees (created at test time via `pytest` tmp paths) for
  each preflight failure mode.
- `test_doctor_json_schema_validates`.
- `test_doctor_does_not_invoke_runner`.
- `test_live_loop_skips_runner_when_preflight_blocks`.
- `test_strict_upgrades_warnings`.
- Exit code matrix test.

**Docs:**

- Diagnostics table mapping code → message → hint, generated from
  source by a small dev script (`scripts/dev-render-diagnostics`) to
  keep docs and code aligned.
- "Before filing a bug" flow: run `revrem doctor --format json` and
  attach the output.

**Migration notes:** introduces exit code 4 and (with `--strict`) 6.
Document in CHANGELOG and `--help`.

**Done when:**

- ≥ 95% of seeded misconfigurations in the fixture set are caught
  pre-launch (matches plan metric).
- `revrem doctor --format json` validates against the published schema.
- Live loop and standalone doctor share the same code path (asserted by
  test).
- `./scripts/dev-check` passes.
- ADR landed.

---

### F4. Artifact Schema V1, Fingerprint, And Fixture Validation

**Branch:** `feat/artifact-schema-v1`

**Plan link:** M2. **Unlocks:** L1; foundational for L2/L3/L4.
**Freezes contract:** artifact schema, fingerprint, canonical JSON,
atomic-write rules (ADR required).

**Purpose:** make run outputs contractual so TUI, replay, reports, CI
comments, and archive work can consume artifacts without parsing
transcripts.

**Blocked by:** F3.

**Primary write set:**

- `src/code_review_loop/artifacts.py` (new)
- `src/code_review_loop/fingerprints.py` (new)
- `src/code_review_loop/cli.py`
- `src/code_review_loop/run_history.py`
- `docs/52-api/README.md` (new — explains schema namespace and stability)
- `docs/52-api/schemas/summary-v1.schema.json`
- `docs/52-api/schemas/diagnostics-v1.schema.json` (extend from F3)
- `docs/52-api/schemas/triage-v1.schema.json` (skeleton, finalized in F6)
- `docs/52-api/schemas/events-v1.schema.json` (skeleton, finalized in F8)
- `docs/52-api/schemas/bug-bundle-v1.schema.json` (skeleton, finalized in F5)
- `tests/test_artifacts.py` (new)
- `tests/test_artifact_schema.py` (new — schema-vs-fixture validation)
- `tests/test_fingerprints.py` (new — golden vectors)
- `tests/fixtures/artifacts/{clear,findings,setup_failure,timeout,check_failure,unknown}/`
- `docs/45-adr/adr-NNN-artifact-schema-v1.md`
- `docs/55-testing/test-001-utility-verification-strategy.md`

**Implementation requirements:**

1. **Artifact writer helper** (`artifacts.py`) implementing
   contracts §1, §2, §4: schema_version stamping, canonical JSON,
   atomic write, path safety.
2. **Fingerprint module** (`fingerprints.py`) implementing contract §3
   with golden test vectors.
3. **JSON Schemas** for summary, diagnostics, triage (skeleton),
   events (skeleton), bug-bundle (skeleton). Validated with
   `jsonschema` (already a dev dep or added under `[dev]`).
4. **Schema diff guard.** For the first v1 schema set, tests validate
   fixtures against schemas and store a baseline copy under
   `docs/52-api/schemas/_history/`. From the next schema change onward,
   `tests/test_artifact_schema.py::test_no_unintentional_breaks` walks
   each schema file, computes a structural diff against the previous version
   on disk, and fails if a breaking change is not paired with a major bump
   and a `CHANGELOG.md` entry.

5. **Updated `summary.json`** includes:
   - `schema_version`;
   - `cli_version` (from `__version__`);
   - `harness`, `harness_version` (when reportable; else `null`);
   - `profile`;
   - `command_line` (redacted of secrets via F5 helpers when
     available; until F5 lands, paths only — no env values);
   - `run_id`, `started_at`, `finished_at`, `duration_seconds`;
   - `phases` summary (counts, durations);
   - `findings` with fingerprints;
   - `artifacts` (relative + absolute paths);
   - `tokens`, `usd` (Decimal-as-string; `null` when unreported).
6. **Raw transcripts** stay in text files; JSON summaries reference
   excerpts and paths, never inlined unbounded text.

**Tests:**

- Golden fixtures for every artifact in every scenario directory.
- Round-trip: write → reload → re-write produces byte-identical bytes.
- Path-traversal attempts in artifact-name inputs are rejected.
- `test_run_history_tolerates_legacy_lines` (forward compatibility).
- Fingerprint stability vectors (rename, whitespace, severity bucketing).
- Decimal money serialization tests.

**Docs:**

- `docs/52-api/README.md` documents the schema namespace, JSON Schema draft,
  stability tiers, and the fact that schema files are machine-readable
  reference artifacts rather than Meminit-governed Markdown docs.
- Each schema documented in `docs/52-api/` with: stability tier,
  whether it can contain user code, retention policy.
- README links to the schema directory.
- ADR records canonical-JSON, atomic-write, fingerprint algorithm.

**Migration notes:** existing run-history readers should already
tolerate unknown keys; verify and document.

**Done when:**

- Every JSON artifact written by a normal or failed run includes
  `schema_version`.
- Fingerprint module is the single source for finding fingerprints.
- Fixture validation is part of `./scripts/dev-check`.
- Consumers no longer need to inspect raw Codex output for summary
  metadata.
- ADR landed.

---

### F5. Redacted Bug Bundles And Failure Fingerprints

**Branch:** `feat/bug-report-bundle`

**Plan link:** M2. **Unlocks:** L1. **Freezes contract:** redaction
defaults (ADR optional but recommended).

**Purpose:** let users share actionable failure diagnostics without
leaking secrets, local transcripts, or proprietary content by default.

**Blocked by:** F4.

**Primary write set:**

- `src/code_review_loop/redaction.py` (new)
- `src/code_review_loop/bug_bundle.py` (new)
- `src/code_review_loop/cli.py`
- `tests/test_redaction.py` (new)
- `tests/test_bug_bundle.py` (new)
- `tests/fixtures/redaction/{clean,poisoned}/`
- `docs/52-api/schemas/bug-bundle-v1.schema.json` (finalize)
- `README.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/45-adr/adr-NNN-redaction-defaults.md` (recommended)

**Implementation requirements:**

1. **`revrem bundle-bug-report <run-dir>`** with:
   - `--output` path option (default `revrem-bug-<run_id>.tar.gz`);
   - `--include-raw-transcripts` opt-in (manifest records the choice);
   - `--no-redact` opt-out, **gated by an explicit
     `--i-understand-the-risks` flag** to discourage accidental
     misuse;
   - JSON manifest at root of the tarball;
   - deterministic file ordering and gzip with `mtime=0` for
     reproducibility.
2. **Redaction by default** per contract §7. Implementation:
   - try `detect-secrets` if installed (extra `[redaction]`);
   - always run a built-in regex pass for: API key patterns
     (AWS, GitHub, OpenAI, Anthropic, generic 32+ hex/base64);
     `Authorization:` headers; PEM private key blocks; `.env`-style
     `KEY=VALUE` assignments; user `$HOME` and `$USER`.
   - replacement token `[REDACTED:<category>]`; idempotent.
3. **Failure fingerprints** for known classes (invalid base, timeout,
   review parsing failure, check command missing, harness executable
   missing) using F4's algorithm with synthetic finding-shaped inputs.
4. **Bundle contents** by default: `summary.json`, `diagnostics.json`,
   sanitized `events.jsonl` (when present, post-F8), check outputs
   (sanitized), profile config (sanitized), `revrem doctor` re-run
   output. **Never** included by default: raw model transcripts,
   non-RevRem files outside the run dir.
5. **Determinism.** A bundle of the same run on the same machine
   produces a byte-identical tarball.
6. **Manifest** validates against `bug-bundle-v1.schema.json`.

**Tests:**

- Poisoned fixture with synthetic secrets must be scrubbed; assert
  none of the original tokens appear in the bundle.
- Bundle manifest test proves no excluded file is included by default.
- `--include-raw-transcripts` flips manifest flag and includes raw
  files (still redacted unless `--no-redact`).
- `--no-redact` without `--i-understand-the-risks` exits with a
  diagnostic and code 4.
- Fingerprints stable across runs in different temp dirs and on
  different usernames.
- Bundle tarball byte-identical across two runs (modulo configured
  inputs).

**Docs:**

- "What to attach to an issue" guidance.
- Warn users not to paste raw transcripts into public issues.
- Document each redaction category and its limits.

**Done when:**

- A failed run can be bundled into a redacted, reproducible archive.
- Synthetic secrets are absent from bundled files.
- Failure fingerprints are searchable, stable, and tied to F4's
  algorithm.

---

### F6. Triage Artifact Contract And Remediation Handoff

**Branch:** `feat/triage-contract`

**Plan link:** M3. **Unlocks:** L2. **Freezes contract:** triage v1
(ADR required).

**Purpose:** turn triage from an optional text pass into structured
guidance that improves remediation without hiding original review
context.

**Blocked by:** F4.

**Primary write set:**

- `src/code_review_loop/triage.py` (new)
- `src/code_review_loop/cli.py`
- `src/code_review_loop/profiles.py`
- `tests/test_triage.py` (new)
- `tests/test_cli.py`
- `tests/test_profiles.py`
- `tests/fixtures/triage/{valid,invalid_json,missing_fields,timeout,rejected_only}/`
- `docs/52-api/schemas/triage-v1.schema.json` (finalize)
- `docs/45-adr/adr-NNN-triage-contract.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/55-testing/test-001-utility-verification-strategy.md`

**Implementation requirements:**

1. **`triage.json` v1** fields:
   - `schema_version`;
   - `source_review_artifact` (relative path);
   - `prompt_version` (so prompt changes are visible in artifacts);
   - `confirmed_findings` — array of `{fingerprint, summary, severity,
     affected_paths, rationale}`;
   - `rejected_findings` — same shape + `rejection_reason`;
   - `needs_more_info` — same shape + `info_requested`;
   - `implementation_order` — array of fingerprints;
   - `verification_commands` — array of strings (operator-authored
     hints; never executed automatically);
   - `parsing_warnings` — non-fatal triage-output anomalies;
   - the F4 envelope fields (`run_id`, etc.) at the top level.
2. **Triage prompt** versioned and stored at
   `src/code_review_loop/prompts/triage_v1.txt`; loaded by
   `triage.py`. Prompt version is included in the artifact.
3. **Validation.** Use `jsonschema` against `triage-v1.schema.json`.
   Invalid output → fail-safe:
   - do not suppress findings;
   - preserve original review;
   - write `diagnostics.json` entry with code
     `revrem.triage.invalid_output`;
   - by default continue to remediation **without** triage guidance,
     emitting a warning. Behavior is configurable via profile
     (`triage.on_invalid: continue|stop`).
4. **Remediation handoff** receives:
   - validated triage guidance (when present);
   - the original review excerpt and path (always).
5. **Profile support** for `triage.enabled`, `triage.model`,
   `triage.on_invalid`, `triage.timeout_seconds`. Validate keys and
   reject unknowns.
6. **Human-readable triage text** preserved alongside `triage.json`
   for terminal summaries.
7. **Fingerprints** in triage entries use F4's algorithm. The same
   fingerprint must appear in the originating review-derived findings
   (assert with a fixture cross-check).

**Tests:**

- Valid triage drives remediation prompt (golden snapshot).
- Invalid JSON / missing required fields fails safe.
- Rejected findings remain visible in artifacts.
- Triage timeout writes diagnostics.
- Profile parsing rejects unknown triage keys and invalid severities.
- Fingerprint cross-check between review and triage.
- Triage precision benchmark stub: a labelled fixture set where the
  test asserts ≥ 0.85 precision (target metric from the plan).

**Docs:**

- When triage helps and when to skip it.
- Triage JSON shape, failure policy, fingerprint linkage.

**Done when:**

- `triage.json` validates against fixtures and schema.
- Remediation handoff includes triage guidance and original review
  context.
- Invalid triage cannot silently hide a real finding.
- Triage-precision benchmark fixture meets ≥ 0.85.
- ADR landed.

---

### F7. Suppression File And `revrem suppress` CLI

**Branch:** `feat/suppressions`

**Plan link:** M3. **Unlocks:** L2. **Freezes contract:** suppression
v1 (ADR required).

**Purpose:** make repeated runs tolerable by allowing explicit,
auditable dismissal of known findings — without becoming a back door
around critical issues.

**Blocked by:** F4 and F6.

**Primary write set:**

- `src/code_review_loop/suppressions.py` (new)
- `src/code_review_loop/cli.py`
- `src/code_review_loop/profiles.py`
- `tests/test_suppressions.py` (new)
- `tests/test_cli.py`
- `tests/fixtures/suppressions/`
- `docs/52-api/schemas/suppressions-v1.schema.json` (new)
- `docs/45-adr/adr-NNN-suppressions.md`
- `README.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`

**Implementation requirements:**

1. **File format.** `.revrem/suppressions.toml` (repo-local default).
   User-local at `~/.config/revrem/suppressions.toml`. Both supported;
   repo-local takes precedence on conflict.
2. **Entry shape:**
   ```toml
   [[suppressions]]
   fingerprint = "f1:abc123…"
   summary     = "SQL injection in user_lookup"
   rationale   = "Tracked in JIRA-1234; mitigation in ingress layer."
   created_at  = "2026-05-09T12:08:23.451Z"
   created_by  = "colin@example.com"
   scope       = "repo"          # repo | user
   severity_at_suppression = "high"
   expires_at  = "2026-08-09T00:00:00Z"   # optional but recommended
   critical_override = false              # required true to suppress critical
   ```
3. **CLI:** `revrem suppress add|list|remove|expire|check`.
   - `add` requires `--rationale`.
   - `add` for a `critical`-severity finding requires
     `--critical-override` and an explicit `--expires` no more than
     30 days out (configurable).
   - `check <fingerprint>` returns exit 0 if suppressed, 2 if not
     (orchestrator-friendly).
4. **Loop integration.** Suppressed findings:
   - remain visible in artifacts (`summary.json` flags them
     `suppressed: true`);
   - emit a `suppressed` event once F8 lands (event kind reserved
     now);
   - do not trigger remediation;
   - do not count as clear unless all unsuppressed findings are clear;
   - mismatched fingerprints (algorithm bump from `f1:` to `f2:`)
     surface as a doctor warning, not a silent miss.
5. **Expiry.** Expired entries are ignored on match and surfaced in
   `revrem doctor` output. `revrem suppress expire` removes them.
6. **Audit log.** Every mutation appends a record to
   `.revrem/suppressions.audit.jsonl` (or user-config equivalent),
   including before/after state and acting user. Bug bundles include a
   redacted audit summary by default. Raw audit logs require explicit
   `--include-raw-transcripts`-style opt-in because rationale text and
   creator identifiers can be sensitive. Document this choice in the ADR.
7. **Profile support** for declaring suppression scope policy
   (e.g., `suppressions.scope: repo`).

**Tests:**

- Add/list/remove/expire round trip.
- Matching and non-matching fingerprint behavior.
- Expiry behavior + doctor surfacing.
- Critical override required and enforced.
- Suppressed finding does not prompt remediation but appears in
  `summary.json` with `suppressed: true`.
- Repo vs user scope precedence.
- Audit log entries match mutations.
- Bug-bundle fixture proves raw audit logs are excluded by default and the
  redacted audit summary contains no email addresses or local paths.
- TOML round-trip preserves comments where library supports it
  (acceptable to lose comments if documented).

**Docs:**

- When suppressions are appropriate and when to fix the underlying
  finding instead.
- Committed (repo) vs user-local trade-offs.
- Strong warning against suppressing security findings without an
  expiry date.
- Audit-log retention guidance.

**Migration notes:** none on first introduction. Future fingerprint
algorithm bumps require an explicit migration tool (out of scope here;
flag for a follow-up task).

**Done when:**

- Re-running against an unchanged, suppressed finding does not
  re-remediate it.
- Suppression entries are auditable and schema-tested.
- Critical findings require explicit override + expiry to suppress.
- Bug bundles cannot leak raw suppression audit rationale by default.
- ADR landed.

---

### F8. Event Sink, `events.jsonl`, And Replay

**Branch:** `feat/event-stream-replay`

**Plan link:** M4. **Unlocks:** L2. **Freezes contract:** event
envelope v1 (ADR required).

**Purpose:** create the event substrate that future TUI, report, CI,
and archive work consume instead of scraping terminal text or model
transcripts.

**Blocked by:** F4. Soft-blocked by F6 (triage events) and F7
(`suppressed` event).

**Primary write set:**

- `src/code_review_loop/events.py` (new)
- `src/code_review_loop/cli.py`
- `src/code_review_loop/progress.py`
- `src/code_review_loop/tui_state.py`
- `tests/test_events.py` (new)
- `tests/test_replay.py` (new)
- `tests/test_cli.py`
- `tests/test_progress.py`
- `tests/test_tui_state.py`
- `tests/fixtures/events/{clear,findings_fixed,rejected_fp,timeout,check_failure,cancellation,cost_ceiling,suppressed}/`
- `docs/52-api/schemas/events-v1.schema.json` (finalize)
- `docs/45-adr/adr-NNN-event-envelope.md`
- `docs/05-planning/plan-002-tui-run-monitor-execution-deferral.md`
  (note replay readiness)
- `docs/55-testing/test-001-utility-verification-strategy.md`

**Implementation requirements:**

1. **Event envelope** per contract §6.
2. **Event kinds (initial):** `phase_start`, `phase_output`,
   `phase_result`, `status_classification`, `check_result`,
   `artifact_write`, `warning`, `failure`, `summary`, `suppressed`,
   `cancellation`, `cost_charge`, `cost_ceiling_hit`. Reserved future
   kinds documented in the schema.
3. **Sink interface** (`EventSink` ABC) with implementations:
   - `InMemorySink` for tests;
   - `JsonlSink` for real runs (buffered, flushed on phase boundaries
     and on failure paths; non-blocking from the loop's perspective);
   - `RendererSink` adapter for compact/Rich progress.
4. **`events.jsonl` per run.** Append-only; LF newlines; one record
   per line. Crash-safe: a partially-written final line on SIGKILL is
   tolerated by the replay reader (treated as truncation; replay stops at the
   last valid line and emits a synthetic `failure` event with
   `payload.reason: "truncated_events_jsonl"`).
5. **`revrem replay <run-dir>`** renders from `events.jsonl` using
   the requested renderer (compact default, Rich/TUI optional).
   Replay never invokes the runner or harness — asserted by test.
6. **Determinism.** Replay of compact renderer is byte-identical to
   the original run's compact output for at least one fixture (sets
   the determinism bar; other renderers may differ on theme).
7. **Logging vs events** per contract §8. Existing `progress.py`
   migrates to consume events; existing log lines retained for
   operator continuity but explicitly out of contract.
8. **Update `REVREM-PLAN-002`** to state TUI execution remains
   deferred until replay fixtures are green.

**Tests:**

- Golden event fixtures for every scenario in the write set.
- Replay compact renderer byte-identical for at least one fixture.
- JSONL append order and `seq` monotonicity (Hypothesis property
  test recommended).
- Truncated-tail tolerance.
- No replay path invokes the runner / harness (monkeypatch trap).
- Renderer sink does not block when paired with a slow consumer
  (timeout test with an artificially slow sink).
- TUI state derives from events (no transcript scraping).

**Docs:**

- Event compatibility rules (additive minor, breaking major).
- Replay as the approved substrate for TUI/report/CI tests.
- ADR.

**Done when:**

- A complete run writes `events.jsonl`.
- `revrem replay` renders fixture runs offline.
- TUI state tests consume replay fixtures or event-derived state.
- No second execution engine has been introduced.
- ADR landed.

---

### F9. Budget Ceilings, Cancellation, And Resume

**Branch:** `feat/budget-cancel-resume`

**Plan link:** M4. **Unlocks:** L2 → L3. **Freezes contract:** budgets
+ exit codes 3/5 (ADR required).

**Purpose:** make hands-off execution bounded enough for hooks and CI
work to start later.

**Blocked by:** F8.

**Primary write set:**

- `src/code_review_loop/budgets.py` (new)
- `src/code_review_loop/cli.py`
- `src/code_review_loop/events.py`
- `src/code_review_loop/run_history.py`
- `tests/test_budgets.py` (new)
- `tests/test_resume.py` (new)
- `tests/test_cli.py`
- `docs/45-adr/adr-NNN-budgets-cancellation.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/55-testing/test-001-utility-verification-strategy.md`

**Implementation requirements:**

1. **CLI / profile options:**
   - `--max-wall-seconds` (int; total run wall-clock ceiling, distinct from
     per-phase `--timeout-seconds`);
   - `--max-tokens` (int);
   - `--max-usd` (Decimal);
   - `--soft-warn-fraction` (float, default 0.8) — emit a `warning`
     event when a ceiling is approached.
   Values default to `null` (no enforcement) for backward compat;
   profiles may set defaults.
2. **Cost data.** Represented as `null` when the harness does not
   report it (never silently `0`). Codex reporting gaps documented
   in the harness adapter.
3. **Ceiling checks** before each model-invoking phase and on each
   `cost_charge` event. A hit emits `cost_ceiling_hit` and stops
   gracefully **before** the next model call; remaining cleanup
   (artifacts, summary, history) still runs.
4. **Cancellation semantics.**
   - First Ctrl-C: drain current phase, kill child process group,
     write artifacts, emit `cancellation`, exit code 5.
   - Second Ctrl-C within 5 s: hard stop, best-effort artifact flush,
     same exit code.
   - SIGTERM: equivalent to first Ctrl-C.
   - Terminal display restored via existing `terminal_recovery_context`.
5. **`revrem resume <run-dir>`** for runs that stopped cleanly after
   a completed phase.
   - Preconditions: worktree HEAD unchanged; base branch unchanged;
     `events.jsonl` ends with a clean phase boundary; profile
     unchanged.
   - Re-uses existing artifacts; never re-runs completed model phases.
   - Failure to satisfy preconditions exits with a diagnostic and code
     4.
6. **Wall-clock vs CPU.** Wall-clock only in this phase; CPU-time
   accounting is out of scope.
7. **Money type** is `Decimal`; serialized as JSON string per
   contract §2.

**Tests:**

- Budget ceiling prevents the next model call (mock harness recording
  call count).
- Soft-warn fires at the configured fraction.
- Missing cost data is `null` not `0`.
- Cancellation writes `events.jsonl`, `summary.json`, diagnostics; no
  orphan child processes (verified by checking PID liveness post-test).
- Resume produces same final summary as a matched uninterrupted
  fixture run.
- Worktree mismatch blocks resume with diagnostic.
- Decimal money round-trips correctly.

**Docs:**

- Budget semantics, limitations, harness reporting gaps.
- Resume safety checks and failure modes.
- Exit code matrix (3, 5) confirmed and cross-linked from F3.

**Done when:**

- Cost and wall-clock ceilings are enforced in tests and across the
  fake harness fixtures from F10 (when both land).
- Cancellation leaves no orphan child process in the regression
  suite.
- Resume is deterministic on fixtures.
- ADR landed.

---

### F10. Fake Harness Contract

**Branch:** `feat/fake-harness-contract`

**Plan link:** M6 (slice). **Unlocks:** prerequisite for L3 secondary
adapters. **Freezes contract:** harness capability surface (ADR
required).

**Purpose:** define executable backend semantics before adding any real
non-Codex adapter.

**Blocked by:** F3. Soft-blocked by F8 (the fake harness reuses event
fixtures for replay).

**Primary write set:**

- `src/code_review_loop/harnesses.py`
- `src/code_review_loop/harness_contract.py` (new)
- `src/code_review_loop/cli.py`
- `src/code_review_loop/profiles.py`
- `tests/test_harnesses.py`
- `tests/test_cli.py`
- `tests/fixtures/harnesses/{review_clear,review_findings,remediation,triage_valid,triage_invalid,timeout,cancellation,unsupported}/`
- `docs/52-api/schemas/harness-capabilities-v1.schema.json` (new)
- `docs/45-adr/adr-NNN-harness-contract.md`
- `docs/70-devex/devex-001-using-code-review-loop.md`
- `docs/55-testing/test-001-utility-verification-strategy.md`

**Implementation requirements:**

1. **Capability surface** — a `HarnessCapabilities` dataclass
   serializable to JSON Schema `harness-capabilities-v1`:
   - `review_supported`, `remediation_supported`, `triage_supported`,
     `commit_message_supported`;
   - `non_interactive`;
   - `sandbox_modes` (list);
   - `timeout_supported`, `cancellation_supported`;
   - `structured_output_supported`;
   - `cost_reporting` (`tokens|usd|none`);
   - `supported_models` (list, may be open-ended);
   - `contract_version` (semver of the contract surface itself).
2. **`fake` harness for tests only.** Never registered for live
   execution by default; explicit opt-in via env
   `REVREM_ALLOW_FAKE_HARNESS=1` for test runs. Replays scripted
   outputs from fixtures; never shells out.
3. **Codex parsing isolation.** Move Codex-specific status parsing
   and command construction behind the harness boundary where
   practical. **Avoid a broad rewrite** — extract only what is
   needed to make the contract testable.
4. **Reserved real harnesses** remain rejected for live execution
   with clear diagnostics referencing F3 codes.
5. **Compatibility test.** A scenario-by-scenario assertion that
   Codex `summary.json` and fake `summary.json` are structurally
   equivalent (same shape, same fields, value differences only
   where harness identity differs).
6. **No real backends in this PR.** Claude/Gemini/opencode/Kilo/
   OpenRouter/HTTP remain explicitly deferred.

**Tests:**

- Fake review clear / findings.
- Fake remediation success / partial.
- Fake triage valid / invalid.
- Fake timeout / cancellation.
- Fake unsupported capability surfaces a diagnostic.
- Reserved real harness rejected for live execution.
- Capability surface validates against schema.
- `summary.json` structural-equivalence test (Codex vs fake on a
  matched fixture).

**Docs:**

- Capability table and semantics.
- Statement that real secondary adapters are gated on this fake
  harness.
- ADR.

**Done when:**

- Harness behavior can be tested without Codex installed.
- Fake harness covers every loop phase.
- Real non-Codex adapters remain unimplemented and explicitly
  deferred.
- ADR landed.

---

## Phase Exit Criteria

This task series is complete when **all** of the following hold:

- F1–F10 are merged (or explicitly superseded by a better governed
  task with a recorded supersession note).
- `./scripts/dev-check`, `pre-commit run --all-files`, and
  `meminit check --format json` pass on `main`.
- A fresh-install smoke exists in CI on Linux + macOS, Python 3.12,
  using the built artifact (or, if PyPI credentials are unavailable,
  a documented dry-run workflow that produces verifiable artifacts).
- `revrem doctor --format json` catches ≥ 95% of seeded
  misconfigurations in the reference fixture.
- `summary.json`, `diagnostics.json`, `triage.json`,
  `events.jsonl`, `bug-bundle.json`, and `suppressions.toml` have
  documented schemas with fixture validation in CI.
- The fingerprint algorithm (`f1:`) is the single source consumed by
  diagnostics, triage, suppressions, bug bundles, and events.
- Suppressions are auditable, expirable, and cannot silently hide
  critical findings.
- `revrem replay` renders event fixtures without model/network
  access; compact-renderer determinism asserted on at least one
  fixture.
- Budget, cancellation, and resume behavior is enforced by tests;
  exit codes 3, 4, 5, 6 are reachable and documented.
- The fake harness contract is green; no real secondary harness has
  been added prematurely.
- Plan success metrics owned by M0–M4 are measured against the
  reference fixture and recorded in
  `docs/55-testing/test-001-utility-verification-strategy.md`.

## Implementation Audit Snapshot

This snapshot records the local completion evidence for the TASK-002 programme.
It is intentionally concrete so a release orchestrator can distinguish
implemented, locally verified work from publication-only gates that require
GitHub/PyPI credentials or a merge to `main`.

| Requirement | Local evidence | Status |
| --- | --- | --- |
| F0 baseline fixture and changelog discipline | `tests/fixtures/reference-repo/`, `tests/test_fixtures.py`, `CHANGELOG.md`, and `REVREM-TEST-001` reference-fixture section. | Implemented locally |
| F1 package identity, metadata, build checks | `pyproject.toml`, `src/code_review_loop/__init__.py`, `.github/workflows/ci.yml`, `tests/test_packaging.py`, `REVREM-ADR-002`. Build backend is pinned and console scripts include `revrem` and `code-review-loop`. | Implemented locally |
| F2 public install smoke and rollback-proof release flow | CI package-smoke installs the built wheel on Linux/macOS for Python 3.11/3.12; release workflow supports dry-run, tag/version validation, Trusted Publishing routing, provenance, checksums, Sigstore, and rollback runbook `REVREM-RUNBOOK-001`; release trust is recorded in `REVREM-ADR-011`. | Implemented locally; live PyPI/TestPyPI publication remains external |
| F3 diagnostics model and `revrem doctor` | `src/code_review_loop/diagnostics.py`, CLI doctor/preflight path, `diagnostics-v1.schema.json`, `scripts/dev-render-diagnostics`, and tests covering the 13/13 current local setup corpus. Exit codes `4` and `6` are directly tested. | Implemented locally |
| F4 artifact schema v1 and fingerprint contract | `src/code_review_loop/artifacts.py`, `src/code_review_loop/fingerprints.py`, schemas in `docs/52-api/schemas/`, `_history` baselines, schema validation tests, and `REVREM-ADR-003` / `REVREM-ADR-004`. | Implemented locally |
| F5 redacted bug bundles and failure fingerprints | `src/code_review_loop/redaction.py`, `src/code_review_loop/bug_bundle.py`, poisoned fixtures, optional `detect-secrets` support, deterministic tarball tests, sanitized profile/preflight snapshot inclusion, and `REVREM-ADR-005`. | Implemented locally |
| F6 triage contract and remediation handoff | `src/code_review_loop/triage.py`, packaged/reference `triage-v1.schema.json`, triage fixtures including invalid, missing-field, rejected-only, and timeout cases, command-failure diagnostics, precision-floor test, profile validation tests, and `REVREM-ADR-006`. | Implemented locally |
| F7 suppression file and CLI | `src/code_review_loop/suppressions.py`, `revrem suppress` CLI tests, schema validation, repo/user precedence, expiry, critical override enforcement, audit summary redaction, bug-bundle integration, and `REVREM-ADR-007`. | Implemented locally |
| F8 event sink, `events.jsonl`, and replay | `src/code_review_loop/events.py`, event fixtures for clear/findings/timeout/check-failure/cancellation/cost-ceiling/suppressed/rejected-finding cases, offline replay tests, TUI state event-reader tests, and `REVREM-ADR-008`. | Implemented locally |
| F9 budgets, cancellation, and resume | `src/code_review_loop/budgets.py`, budget ceiling tests, fake-harness token-charge tests, cancellation diagnostics/events/summary tests, resume precondition tests, exit codes `3`, `4`, and `5`, and `REVREM-ADR-009`. | Implemented locally |
| F10 fake harness contract | `src/code_review_loop/harnesses.py`, `harness-capabilities-v1.schema.json`, fake harness fixtures, env-gated fake harness behavior, reserved non-Codex harness rejection, Codex/fake summary shape equivalence, and `REVREM-ADR-010`. | Implemented locally |
| Required local gates | `./scripts/dev-check` passed with 392 tests; `pre-commit run --all-files` passed; `meminit check --format json` passed via both gates. | Verified locally |
| Main-branch and publication gates | This branch has not been pushed or merged by this agent. Actual TestPyPI/PyPI publish, GitHub Release artifact attachment, and branch-protection/main-branch status must be performed by the release operator after review. | External/manual gate |

## ADR Closure

By phase end, the following ADRs exist (numbers assigned at
`meminit new` time):

- ADR — Package identity (F1).
- ADR — Release trust and provenance (F2).
- ADR — Diagnostic model and exit codes (F3).
- ADR — Artifact schema v1, canonical JSON, atomic writes,
  fingerprint algorithm (F4).
- ADR — Redaction defaults (F5, recommended).
- ADR — Triage contract (F6).
- ADR — Suppressions (F7).
- ADR — Event envelope v1 (F8).
- ADR — Budgets and cancellation (F9).
- ADR — Harness capability surface (F10).

The ADR set is the durable record of every contract this phase
freezes. A future contract change must supersede the relevant ADR
rather than amend silently.

## Readiness For The Next Phase

After this task series, the following work becomes eligible
(tracked in `REVREM-PLAN-003` milestones M5+ and a future TASK doc):

- TUI-launched real runs using `events.jsonl` and replay fixtures.
- Hook / headless mode with stable exit codes.
- Static HTML reports from run artifacts (`revrem report`).
- GitHub Action / PR comment surface.
- First real secondary harness adapter (Claude CLI preferred).
- Expert profile bundle and showcase demo capture.
- Indexed remediation archive + dataset export.

If any of those are attempted before the relevant F-task is
complete, the PR should be rejected or split.

## Resolved Decisions

The original open questions for F1/F4/F6/F7/F8/F9/F10 are resolved by
the implemented ADRs and tests:

- **F1 package identity:** `REVREM-ADR-002` chooses `revrem` as the public
  distribution name while retaining `code-review-loop` as a console-script
  alias for continuity.
- **F4 command-line artifact field:** `summary.json` reserves
  `command_line` but currently records `null`; future population must pass
  through the F5 redaction helpers rather than writing raw argv/env-derived
  values.
- **F6 invalid triage policy:** `REVREM-ADR-006` and profile validation use
  `triage.on_invalid = "continue"` by default, with `stop` available for strict
  workflows. Invalid and failed triage artifacts write diagnostics.
- **F7 suppression scope:** `REVREM-ADR-007` makes repo-local suppressions the
  default shared scope and gives repo entries precedence over user-local
  entries.
- **F8 event envelope convention:** `REVREM-ADR-008` uses a bespoke, minimal
  event envelope for this phase instead of CloudEvents; interop can be
  reconsidered if the CI/Action surface later needs it.
- **F9 money units:** `REVREM-ADR-009` treats `--max-usd` as USD-only and
  serializes money as decimal strings; non-USD reporting is deferred until a
  harness actually supplies it.
- **F10 fake harness gating:** `REVREM-ADR-010` and the harness tests gate the
  fake harness behind `REVREM_ALLOW_FAKE_HARNESS=1`; real secondary adapters
  remain explicitly deferred.
