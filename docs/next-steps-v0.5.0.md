---
document_id: REVREM-PLAN-005
type: PLAN
title: Next steps — v0.5.0 (Showcase & Hands-Off Adoption)
status: Draft
version: '0.1'
last_updated: '2026-06-18'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: PR-sized implementation programme for RevRem v0.5.0, turning the hardened v0.4.0 foundation into a team-adoptable, screenshot-worthy showcase — static HTML run reports, a reference GitHub Action with idempotent PR comments, a bundled expert-profile suite, and public DevEx expansion. Closes the open PLAN-003 milestones M7 and M8 and finishes the last M5 slice.
keywords:
- revrem
- roadmap
- v0.5.0
- report
- github-action
- ci
- expert-profiles
- devex
- showcase
- hands-off
related_ids:
- REVREM-PLAN-003
- REVREM-PLAN-002
- REVREM-PRD-001
- REVREM-DEVEX-001
- REVREM-TEST-001
- REVREM-TASK-002
- REVREM-FDD-001
- REVREM-ADR-008
- REVREM-ADR-011
---

> **Document ID:** REVREM-PLAN-005
> **Owner:** GitCmurf
> **Status:** Draft
> **Type:** PLAN
> **Area:** planning
> **Description:** Implementation programme for RevRem v0.5.0 — "Showcase & Hands-Off Adoption".

# PLAN: Next steps — v0.5.0 (Showcase & Hands-Off Adoption)

## How To Read This Document

This is an engineering handover written so that a fast, inexpensive model can
execute most of the implementation with little additional context. It assumes
the reader is an agentic coding orchestrator (or a human assigning work).

Read in this order:

1. **Where We Are** and **Why v0.5.0 Is This** — the state of the repo today and
   the rationale for the chosen scope.
2. **Scope, Non-Goals, and Maturity** — what ships and what is explicitly out.
3. **Shared Contracts** — cross-cutting rules every task must obey. Do not skip.
4. **Dependency Graph & Traceability** — task order and how each ladders up to
   `REVREM-PLAN-003` milestones and success metrics.
5. **Tasks T0–T13** — PR-sized work packages, each with concrete file paths,
   step-by-step implementation notes, acceptance criteria, tests, and docs.
6. **Release & Exit Criteria** — how we know v0.5.0 is done.

If a task and the Shared Contracts section disagree, **the contracts win**.

## Where We Are (Baseline, 2026-06-18)

RevRem is at **v0.4.0**, released today. The governing roadmap
`REVREM-PLAN-003` ("Post-Launch Development Roadmap") sequences work across
three tracks (Trust, Workflow, Showcase) up to a 1.0 "boring infrastructure"
target. As of v0.4.0, the foundation is far more complete than the roadmap's
original version table assumed:

- **Done:** M0 (public trust baseline), M1 (PyPI/pipx/provenance), M2 (doctor,
  diagnostics, artifact schema v1), M3 (triage productization + suppressions),
  M4 (event stream + cost governance + replay), and M6 (harness contract + fake
  harness + Codex/Claude/Gemini/opencode/Kilo adapters + routing).
- **Mostly done (M5):** `revrem install-hooks`, `revrem checks suggest`,
  `revrem resume`, headless exit codes, and the `RendererSink` event adapter all
  shipped. The TUI renders Home/Profiles/Pipeline/Run Monitor/Controls views but
  **does not yet start real runs** — the CLI remains the only execution path.
- **Not started:** **M7** (bundled expert profiles + public DevEx expansion),
  **M8** (hands-off CI surface + static HTML report), **M9** (distillation
  archive + daemon + dataset export).

All seven dependency gates in `REVREM-PLAN-003` (G1 distribution smoke, G2
diagnostic schema, G3 suppression semantics, G4 budget enforcement, G5 event
replay, G6 fake-harness contract, G7 redaction harness) have **landed**. That
means Track C (M7 → M8) and the final M5 slice are fully unblocked.

## Why v0.5.0 Is This

The roadmap's North Star is "the local, watched, evidence-producing
review-and-remediation loop that a developer trusts to run hands-off on their
branch — and trusts enough to publish what it found." The 1.0 showcase demo it
defines has seven steps; RevRem can already do steps 1–4 and 6–7 (install,
profile run, preflight, bounded loop, suppressions, schema-versioned artifacts).
The two missing showcase capabilities are both in step 5:

> "The same run can be replayed in compact terminal output, Rich/TUI output,
> **static HTML report, and CI comment** without re-running a model."

That gap is precisely M7 + M8. Closing it is the highest-value next step because
it converts RevRem from "a CLI a solo developer runs" into "a tool a team drops
into CI and a stranger screenshots from a PR comment" — the L3 rung of the
autonomy ladder, and the single biggest lever on external adoption. Every input
it needs already exists: the event stream (`events.jsonl`), the frozen artifact
schema (`summary-v1`), the replay substrate, the redaction helper, and bounded
budgets.

Per the `REVREM-PLAN-003` Decision Matrix, the items bundled here are its
highest-ranked unshipped work: expert profiles (High value / High showcase),
static HTML report (High showcase), GitHub Action (High value / High showcase),
and public DevEx polish (P1, High showcase).

**v0.5.0 theme:** *Showcase & Hands-Off Adoption.* One engine, more lenses
(expert profiles) and more surfaces (HTML report, CI Action), with no new
execution path and no weakening of the bounded/diagnosable/local-first posture.

## Scope

v0.5.0 ships five pillars. Each pillar is independently shippable; pillars A–D
are committed, pillar E is a stretch that may slip to v0.6.0 without blocking
the release.

- **Pillar A — `revrem report` (static HTML run report).** A new read-only
  subcommand that renders `summary.json` + `events.jsonl` into a single
  self-contained HTML file. (PLAN-003 M8, part 1.)
- **Pillar B — Reference GitHub Action + headless CI hardening.** A composite
  Action that installs `revrem`, runs a profile against PR head vs. base,
  uploads the run directory and HTML report, and posts one idempotent PR
  comment. (PLAN-003 M8, part 2.)
- **Pillar C — Bundled expert profiles.** `security`, `performance`, `refactor`,
  `test-gap`, and `docs` profiles, each with a tuned review/triage rubric, a
  recommended check matrix, severity policy, and a fixture set it is known to
  flag — invokable as `revrem --profile security`. (PLAN-003 M7, part 1.)
- **Pillar D — Public DevEx expansion.** An `examples/` matrix, a maintained
  demo recording pipeline, shell completions, a failure-diagnostics guide, and
  seeded "good first issues". (PLAN-003 M7, part 2.)
- **Pillar E (stretch) — TUI starts real runs.** Wire the existing Textual UI to
  launch, monitor, and cancel real runs through the application boundary,
  reusing the event stream. (PLAN-003 M5, final slice.)

## Non-Goals (v0.5.0 Anti-Scope)

These are explicitly out of v0.5.0. Several are M9 and stay deferred; the rest
protect the showcase from scope creep.

- **No distillation archive, dataset export, or `revrem watch` daemon** (M9).
- **No hosted service, telemetry, or off-machine upload.** The Action uploads
  only to the repo's own CI artifact store and posts a comment using the repo's
  own token; nothing leaves the user's infrastructure by default.
- **No second execution engine.** `revrem report` and the Action are *consumers*
  of artifacts; the TUI run path (Pillar E) calls the existing application
  boundary. `runner.run_loop()` / the core engine remains the only owner of
  review/remediation execution. (PLAN-003 final-review correction, restated in
  `REVREM-TASK-002`.)
- **No new model providers / harnesses.** M6 is closed; v0.5.0 adds lenses, not
  backends.
- **No JS framework in the HTML report.** Plain HTML + inline CSS only, so the
  report is a single file safe to upload as a CI artifact and open offline.
- **No auto-editing of user profiles or hooks** beyond the existing opt-in
  `install-hooks`; expert profiles are read-only built-ins the user selects.

## Capability Maturity Targets

Using the `REVREM-PLAN-003` maturity ladder (Experimental → Preview →
Default-on-local → Default-on-hands-off → Stable contract):

| Capability | Target maturity at v0.5.0 |
|---|---|
| `revrem report` HTML | Default-on for local use (documented, schema-validated inputs, fixture-tested) |
| GitHub Action + PR comment | Preview (documented, reference repo smoke, least-privilege tokens) |
| Expert profiles | Preview (documented, fixture suite proves distinct findings; not yet SemVer-frozen) |
| Examples / completions / demo | Default-on for local use |
| TUI real runs (stretch) | Experimental (flagged; Pilot-tested replay before live runs) |

The HTML report **input** contract is the only frozen surface: it reads the
already-frozen `summary-v1` and `events-v1` schemas. The report's *HTML layout*
is explicitly not a stable contract until PLAN-003 0.9.0.

## Shared Contracts

Every task in this plan must obey these. They mirror the cross-cutting rules in
`REVREM-TASK-002` and the architecture boundaries enforced by `import-linter`
in `pyproject.toml`.

1. **Atomic unit of work.** Each task is one PR carrying code + tests + docs
   (public *or* governed) + pasted local verification evidence. A task is not
   "done" until `./scripts/dev-check`, `pre-commit run --all-files`,
   `meminit check --format json`, and `git diff --check` all pass.

2. **Architecture boundaries (import-linter).** New code must respect the
   contracts in `pyproject.toml [tool.importlinter]`:
   - `code_review_loop.core` (engine/ports/state/outcome) stays a dependency-free
     decision layer — it must not import adapters, cli, runner, profiles,
     terminal, tui, or argparse.
   - CLI subcommands route through the application boundary, not `runner`
     internals. New commands live under `src/code_review_loop/cli/commands/` and
     register in `cli/commands/registry.py`.
   - Read-only consumers (report, Action helpers) import `events` and read
     `summary.json`; they must not import `runner` or re-execute phases.
   Run `lint-imports` (import-linter) as part of `dev-check`; a new module that
   violates a contract fails CI.

3. **Read-from-artifacts, never re-run.** `revrem report` and any CI helper
   derive everything from `summary.json` + `events.jsonl` in a run directory.
   They never invoke a model, never touch the network, and never need Codex.
   This is gate **G5** (event replay) extended to a new renderer.

4. **Redaction is on by default for anything that leaves the run dir.** Reuse
   `src/code_review_loop/redaction.py` (the same helper behind
   `bundle-bug-report`). The HTML report, the PR comment body, and any uploaded
   summary must be scrubbed unless the operator passes an explicit
   `--no-redact --i-understand-the-risks` pair (gate **G7**).

5. **Bounded by default.** The Action must pass through `--max-iterations`,
   `--max-wall-seconds`, `--max-tokens`, and `--max-usd`, and refuse to run an
   unbounded loop in CI without an explicit opt-in flag. Cost ceilings already
   stop before the next model call (exit code `3`); the Action surfaces that
   state, it does not bypass it.

6. **Stable exit codes (do not change).** `0` clear · `1` utility error · `2`
   findings/pending check failures · `3` budget ceiling · `4` setup/resume
   precondition · `5` cancelled · `6` `doctor --strict` warnings. New surfaces
   *map* these codes; they never redefine them.

7. **JSON output is additive-only.** Any new machine-readable output (e.g. a
   `report --format json` index, or an Action summary) follows the `summary-v1`
   conventions: canonical JSON via `artifacts.canonicalize_json`, a
   `schema_version` field, additive changes only within the major version.

8. **New schemas get a versioned file + history baseline + fixtures.** If a task
   introduces a new artifact (e.g. an expert-profile manifest), add
   `docs/52-api/schemas/<name>-v1.schema.json`, an `_history/` baseline, and
   fixture validation tests, exactly like the existing schemas.

9. **Determinism.** Generated artifacts (HTML, completions, dataset-free
   exports) must be byte-stable given the same inputs: sort keys, pin
   timestamps to values read from `summary.json`/events (never `now()` at render
   time), and avoid embedding absolute worktree paths. Golden-file tests enforce
   this. Mark any unavoidable nondeterminism with a `det-exempt:` comment, as
   the codebase already does in `events.py`.

10. **Docs move with code.** Update `REVREM-DEVEX-001` (operator guide) and the
    README for every user-visible surface; update `REVREM-TEST-001` with new
    verification gates; record any contract decision as an ADR
    (`REVREM-ADR-0NN`).

## Dependency Graph

```text
T0 (governance + fixtures + metrics)
 ├─> Pillar A:  T1 (report core) ──> T2 (report sections + golden HTML)
 │                                     │
 ├─> Pillar B:  T3 (headless/CI hardening) ──> T4 (GitHub Action + PR comment)
 │                                     ▲           (consumes T2 report)
 │                                     └───────────┘
 ├─> Pillar C:  T5 (expert-profile loader) ──> T6 (profile content) ──> T7 (fixture suite + overlap metric)
 │
 ├─> Pillar D:  T8 (examples/)   T9 (demo pipeline)   T10 (completions)   T11 (diagnostics guide + FGIs)
 │
 └─> Pillar E:  T12 (TUI real runs — stretch)

T13 (release: version bump, CHANGELOG, schema-freeze notes, tag) depends on all committed tasks.
```

Within a pillar, tasks are serial. Across pillars, they are independent and may
land in any order once **T0** lands. T4 (Action) depends on **T2** (a renderable
report) and **T3** (headless stability). T7 depends on **T6**. Everything else
is parallelizable.

## Traceability To PLAN-003

| Task | PLAN-003 milestone | Theme | Success metric moved |
|---|---|---|---|
| T1, T2 | M8 (report) | Distillation, Craft | "HTML report reproducible from stored `events.jsonl`" |
| T3 | M5 (headless) / M8 | Autonomy, Trust | "Headless output grep-able, ANSI-free off-TTY" |
| T4 | M8 (CI surface) | Autonomy, Craft | "Hands-off CI posts useful comment ≤ 5 min on 1k-LOC PR" |
| T5, T6, T7 | M7 (expert profiles) | Versatility, Craft | "≥ 4 profiles, ≤ 20% finding overlap on a contrived bug suite" |
| T8, T9, T10, T11 | M7 (DevEx) | Craft | "good first issue → first external PR merged ≥ 3 by 1.0" |
| T12 (stretch) | M5 (TUI runs) | Autonomy, Craft | "TUI-launched run == CLI run artifacts" |

## Reference Facts For Implementers

Concrete anchors so a fast model does not have to rediscover them:

- **Package layout:** `src/code_review_loop/` (src layout; console scripts
  `revrem` and `code-review-loop` both map to `code_review_loop.cli.main:main`).
- **Subcommand registration:** add new commands to the dict returned by
  `build_subcommand_registry()` in
  `src/code_review_loop/cli/commands/registry.py`. Each handler has signature
  `main(argv: Sequence[str]) -> int` and returns an exit code via
  `cli.outcome.CommandOk()/CommandFailed(exit_code=...)`.
- **Arg parsing:** per-command parsers live in `src/code_review_loop/cli/args.py`
  (e.g. `parse_replay_args`). Add `parse_report_args` there.
- **Closest template for a new read-only command:**
  `src/code_review_loop/cli/commands/replay.py` (reads `events.jsonl`, renders,
  maps truncation to an exit code).
- **Event stream API (`src/code_review_loop/events.py`):**
  `EVENTS_FILENAME = "events.jsonl"`; `read_events(path) -> (records, truncated)`;
  `render_compact(records) -> str`; `EVENT_KINDS` includes `phase_start`,
  `phase_result`, `status_classification`, `check_result`, `artifact_write`,
  `warning`, `failure`, `summary`, `suppressed`, `cost_charge`,
  `cost_ceiling_hit`, `routing_decision`, `routing_outcome`; `Event` is a frozen
  dataclass with `run_id, seq, kind, phase, iteration, payload, ts,
  schema_version`.
- **Summary building:** `src/code_review_loop/reporting.py` owns `summary.json`
  construction (`write_summary`, `phase_config_payload`,
  `external_review_coverage_payload`, `summary_budget_payload`, artifact-path
  collection). The report renderer *reads* the finished `summary.json`; it does
  not call these.
- **Redaction:** `src/code_review_loop/redaction.py`.
- **Profiles:** `src/code_review_loop/profiles.py` (parsing, validation,
  import/export, config writes), `config.py`, `cli/config_builder.py`. Built-in
  `default` and `dogfood` profiles already exist; user profiles in
  `~/.config/revrem/profiles.toml`, project-local `.revrem.toml`.
- **Prompts & fragments:** `src/code_review_loop/prompts/{triage_v1,triage_v2}.txt`
  and `src/code_review_loop/prompts/fragments/*.txt` (current fragments:
  `architecture-checklist`, `atomic-task-list`, `definition-of-done`,
  `engineering-principles`, `regression-test-checklist`, `security-checklist`).
  Packaged via `[tool.setuptools.package-data]` in `pyproject.toml`.
- **TUI:** `src/code_review_loop/tui.py`, `tui_state.py` (views: Home, Profiles,
  Pipeline, Run Monitor, Controls). Dependency-gated behind the `tui` extra.
- **Application/headless boundary:** `src/code_review_loop/application.py`;
  loop owner `runner.py` / `core/engine.py`.
- **Schemas:** `docs/52-api/schemas/*.schema.json` with `_history/` baselines.
- **Schema README:** `docs/52-api/README.md`.
- **Existing fixtures:** golden artifact scenarios (clear, findings,
  setup-failure, timeout, check-failure, unknown-review) and replay fixtures
  already exist under `tests/`; reuse them as report/Action inputs.

---

## Task T0 — Milestone bootstrap, fixtures, and success metrics

**Goal.** Stand up the governance and shared test inputs the rest of v0.5.0
consumes, so later tasks are pure feature work.

**Why first.** Every downstream task needs (a) a place in the governed planning
tree, (b) a stable set of finished run-directory fixtures to render/upload, and
(c) the contrived multi-issue repository the expert-profile overlap metric is
measured against.

**Implementation steps.**

1. Migrate this document to the governed planning tree as
   `docs/05-planning/plan-005-next-steps-v0.5.0.md` (this is required, not
   optional — all governed planning docs live under `docs/05-planning/` and
   must be created or registered via Meminit). Update the MEMORY.md pointer
   accordingly. Confirm `meminit check --format json` passes with the
   front-matter above (document_id `REVREM-PLAN-005`). This is the very first
   action in T0 because downstream tasks reference this document's stable path.
2. Create a **finished-run fixture catalogue** under
   `tests/fixtures/runs/` (reuse the existing golden artifact scenarios). Ensure
   each scenario directory contains a valid `summary.json` and `events.jsonl`
   for at least: `clear`, `findings_remediated`, `findings_remaining`,
   `timeout`, `check_failure`, `cost_ceiling`, `cancelled`, and
   `all_suppressed`. Add a small loader helper `tests/support/run_fixtures.py`
   exposing `load_run(name) -> Path` so T1/T2/T4 share inputs.
3. Create the **contrived multi-issue reference repo** fixture under
   `tests/fixtures/expert_repo/` (or extend the existing reference fixture
   repository noted in the v0.4.0 changelog). It must contain seeded issues that
   map to each expert profile: at least one security bug (e.g. unsafe
   deserialization / hardcoded secret), one performance bug (e.g. an N+1 / hot
   allocation), one refactor smell (duplication / dead code), one test gap
   (changed-but-uncovered branch), and one docs drift (docstring contradicts
   code). Record expected-flag metadata in
   `tests/fixtures/expert_repo/EXPECTED.json` keyed by profile.
4. Record the v0.5.0 **success-metric targets** (copied from PLAN-003 plus the
   two new ones below) in a short "Metrics" section appended to this doc or in
   `REVREM-TEST-001`:
   - HTML report renders a stored run in < 1 s and validates structurally.
   - Action posts a comment within 5 min on a 1k-LOC reference PR.
   - ≥ 4 expert profiles produce distinct findings with ≤ 20% overlap on the
     contrived repo.

**Acceptance criteria.**
- `meminit check --format json` passes with REVREM-PLAN-005 registered.
- `tests/support/run_fixtures.py::load_run` returns a directory with both
  `summary.json` and `events.jsonl` for every named scenario.
- `tests/fixtures/expert_repo/EXPECTED.json` enumerates ≥ 5 seeded issues with
  the profile expected to flag each.

**Tests.** A meta-test asserts every fixture run directory's `summary.json`
validates against `summary-v1.schema.json` and `events.jsonl` validates against
`events-v1.schema.json`.

**Docs.** This plan registered in Meminit; `REVREM-TEST-001` references the new
fixture catalogue.

**Cheap-model suitability:** High. Mechanical fixture assembly and registration.

---

## Task T1 — `revrem report` core (events + summary → HTML)

**Goal.** Add a read-only `revrem report <run-dir>` subcommand that emits a
single self-contained HTML file from a finished run.

**Files.**
- New: `src/code_review_loop/report_html.py` — the renderer (pure function:
  inputs → HTML string).
- New: `src/code_review_loop/cli/commands/report.py` — the command handler
  (mirror `cli/commands/replay.py`).
- Edit: `src/code_review_loop/cli/commands/registry.py` — add
  `"report": report.main` to `build_subcommand_registry()` and its import block.
- Edit: `src/code_review_loop/cli/args.py` — add `parse_report_args(argv)`
  supporting `run_dir` (positional), `--output/-o <path>` (default
  `<run-dir>/report.html`), `--format {html,json}` (default `html`), and the
  redaction opt-out pair `--no-redact` + `--i-understand-the-risks`. Do not
  add `--open` — a no-op placeholder is not acceptable API design; add it only
  if there is a real implementation ready to ship.

**Implementation steps.**

1. In `report_html.py`, define
   `render_report(summary: dict, events: list[Event], *, redact: bool = True) -> str`.
   Read inputs in the command, not the renderer, to keep `render_report` pure
   and trivially testable.
2. Build the HTML as plain HTML5 + inline `<style>` (no external assets, no JS).
   Use a small internal template-string helper; escape all interpolated text
   with `html.escape`. Sections, in order:
   - **Header:** run id, final status badge (clear/findings/unknown/failure/
     cost-ceiling — distinct colours), base ref, HEAD, profile, harness/model
     per phase (from `summary.phase_config`), wall-clock duration, exit-code
     mapping.
   - **Outcome summary:** `stopped_reason`, iteration count, check pass/fail
     tally, suppressed-finding count.
   - **Body sections** are filled in by T2 (findings, triage, checks, cost,
     diff stats). T1 may stub these with placeholders.
   - **Footer:** RevRem version, schema versions consumed, "rendered from
     events.jsonl — no model was re-run" provenance line, and a redaction notice.
3. In `cli/commands/report.py::main`, parse args, resolve the run dir, read
   `summary.json` (via `json`/`artifacts`) and
   `events.read_events(run_dir / events.EVENTS_FILENAME)`. On `--format json`,
   emit a small machine index (`schema_version`, run id, status, counts,
   artifact paths) instead of HTML. Apply redaction to all rendered text when
   `redact` is true (default).
4. Exit-code mapping: `0` on success; `1` on missing/invalid inputs (mirror
   `replay.py`'s error handling); if `events.jsonl` is truncated, still render
   what is available and print a warning to stderr (do not fail the render —
   the report is diagnostic).
5. Resolve `--output` relative to the current working directory; never write
   outside it without an explicit absolute path. Write atomically (reuse
   `artifacts` write helpers / temp-then-rename).

**Acceptance criteria.**
- `revrem report <run-dir>` writes `report.html` and exits `0` for every T0
  fixture run.
- The HTML is a single file (no external references), opens offline, and
  contains the run id and final status.
- `revrem report <run-dir> --format json` prints canonical JSON with a
  `schema_version`.
- No model, network, or Codex access occurs (enforced by a test that runs the
  command with network blocked / Codex absent).
- `render_report` is importable and callable without touching disk.

**Tests.**
- `tests/test_report_html.py`: for each T0 fixture, render and assert key
  substrings (run id, status badge text, provenance footer) are present and
  that output is deterministic (render twice, assert byte-equal).
- Redaction test: a fixture containing a synthetic secret is scrubbed in the
  rendered HTML by default and present only with `--no-redact
  --i-understand-the-risks`.
- Truncated-`events.jsonl` test: renders with a warning, exits `0`.

**Docs.** Add a "Static HTML report" subsection to `REVREM-DEVEX-001` and a
short README mention under Key Features.

**Cheap-model suitability:** High. Self-contained, with `replay.py` as a direct
template and pure-function rendering.

---

## Task T2 — Report content sections, golden HTML, and diff stats

**Goal.** Fill the report body with the substance a reviewer wants, and lock it
with golden-file tests.

**Files.**
- Edit: `src/code_review_loop/report_html.py` (extend `render_report`).
- New: `tests/golden/report/*.html` (golden outputs per fixture).
- Edit: `tests/test_report_html.py`.

**Implementation steps.**

1. **Findings & triage section.** From `summary.json` artifact paths and any
   `triage-N.json` present in the run dir, render confirmed findings (severity,
   path/module, one-line summary, fingerprint `f1:`), rejected findings with
   rationale, `needs_more_info` items, and suppressed findings (clearly marked,
   with suppression provenance). Keep prose excerpts short and escaped.
2. **Checks section.** From `summary.iterations[].checks` /
   `check_attempts` and `check_result` events: command, status, return code,
   artifact link (relative path), and inner-retry history when present.
3. **Cost & budget section.** From `summary` budget payload and `cost_charge` /
   `cost_ceiling_hit` events: tokens, USD, wall-clock spent vs. ceilings.
   Render `null` honestly (do not show `0` when the harness cannot report).
4. **Diff stats section.** From `git diff --stat`-style data already captured in
   artifacts/events where available; if not present in the run dir, render
   "diff stats unavailable for this run" rather than recomputing from git (the
   report must not shell out).
5. **Timeline.** A compact ordered list of phase_start/phase_result events
   (reuse the event ordering that `render_compact` relies on) so the reader can
   follow the loop.
6. Add **golden-file tests**: render each T0 fixture to HTML and compare against
   a checked-in golden file. Provide an update affordance
   (`REVREM_UPDATE_GOLDEN=1`) consistent with how the repo updates other golden
   fixtures. Goldens must be deterministic (Contract #9).

**Acceptance criteria.**
- For a `findings_remediated` fixture, the report shows the original finding,
  its triage classification, the applied check results, and the final clear
  status.
- For an `all_suppressed` fixture, suppressed findings are visible and labelled,
  and the report shows the `all_findings_suppressed` stop reason.
- For a `cost_ceiling` fixture, the cost section shows the ceiling breach and
  the report header badge reflects the budget-stop state.
- Golden HTML files match byte-for-byte across two runs and across Linux/macOS.

**Tests.** Golden comparisons for ≥ 6 fixtures; a redaction golden; a
"diff stats unavailable" path.

**Docs.** Expand the `REVREM-DEVEX-001` report subsection with a screenshot or
fixture reference and a description of each section.

**Cheap-model suitability:** Medium-High. Repetitive section rendering; golden
tests catch mistakes.

---

## Task T3 — Headless / CI output hardening

**Goal.** Make non-interactive runs perfectly clean for CI capture so the Action
(T4) can rely on them. This finishes the headless slice of PLAN-003 M5.

**Files.**
- Edit: `src/code_review_loop/progress.py` (TTY detection / ANSI suppression),
  `src/code_review_loop/cli/args.py` (flag), `cli/outcome.py`/`cli/exit.py`
  (verify code mapping), and `reporting.py` if a stdout JSON summary needs a
  stable shape.

**Implementation steps.**

1. Confirm/here-implement `--no-tty` (and auto-detection when stdout is not a
   TTY): disable progress animation, terminal-title escapes, and all ANSI, and
   emit stable line-oriented logs. If this already exists from M5, add a test
   that asserts **zero** ANSI escape bytes when stdout is not a TTY and document
   it; if it does not, implement it in `progress.py`.
2. Guarantee the documented exit codes (Contract #6) are emitted on every
   terminal path in headless mode, including `3` (ceiling), `4` (setup/resume),
   `5` (cancel). Add a parametrized test mapping each scenario fixture to its
   exit code.
3. Provide a **machine run-summary on stdout** suitable for CI logs:
   `--summary-format json` already exists; verify it prints canonical
   `summary.json` content and add a `--summary-format both` ordering test so a
   CI step can both show humans a compact summary and capture JSON.
4. Ensure `events.jsonl` and `summary.json` are always written before process
   exit on every terminal path (already true for most; add coverage for the
   headless cancel path).

**Acceptance criteria.**
- With stdout redirected to a file, output contains no ANSI escape sequences and
  is greppable line-by-line.
- Each scenario fixture exits with its documented code under `--no-tty`.
- `--summary-format json` output validates against `summary-v1.schema.json`.

**Tests.** `tests/test_headless_output.py` (ANSI-free assertion, exit-code
matrix, JSON summary validation).

**Docs.** Update the "Current CLI boundary" / "Exit codes" sections of
`REVREM-DEVEX-001` to state the headless guarantees explicitly.

**Cheap-model suitability:** Medium. Mostly verification + small guards; the
risk is touching shared progress code, so keep changes additive and well-tested.

---

## Task T4 — Reference GitHub Action + idempotent PR comment

**Goal.** A reference Action that runs RevRem on a PR and leaves a single,
updating PR comment plus uploaded artifacts — turning RevRem into ambient
infrastructure (L3).

**Files.**
- New: `action.yml` (composite action at repo root) — or `.github/actions/revrem/action.yml`
  if kept namespaced; document the choice (see PLAN-003 OQ5).
- New: `.github/workflows/revrem-pr.yml` — a reference workflow that uses the
  action on this repo's own PRs (dogfood).
- New: `scripts/ci/post_pr_comment.py` — a small, dependency-light script that
  reads `summary.json` (+ optional `report.html` link) and posts/updates one PR
  comment via the GitHub REST API using `GITHUB_TOKEN`.
- New: `docs/52-api/` note or `REVREM-DEVEX-001` section documenting the Action
  contract and least-privilege permissions.

**Implementation steps.**

1. **Composite action (`action.yml`).** Inputs: `base` (default `origin/main`),
   `profile`, `max-iterations`, `max-wall-seconds`, `max-usd`, `max-tokens`,
   `checks` (newline list), `comment` (bool, default true),
   `upload-artifacts` (bool, default true), `raw-artifacts` (bool, default
   false — see artifact upload note below), `install-mode` (`pypi` or `local`,
   default `pypi` — see dogfood note below). Steps:
   - **Install:** when `install-mode == pypi`, install via
     `pipx install revrem==<pinned>`; when `install-mode == local`, run
     `pip install -e .` against the checked-out source. The dogfood workflow
     uses `local` so v0.5.0 can be validated before its PyPI package exists.
     Document both modes clearly.
   - **Run:** `revrem --base "$base" --profile "$profile" --no-tty
     --summary-format json --max-iterations ... --max-wall-seconds ...
     --max-usd ...`. **Do not pass `--artifact-dir`**: the runner generates a
     timestamped concrete run directory under `.revrem/runs/` by default
     (see `default_artifact_dir()` in `cli/config_builder.py`). Capture the
     actual run directory from the `--summary-format json` output
     (`artifact_dir` field) or by globbing `.revrem/runs/` for the newest
     entry. Never hard-code `.revrem/runs/ci/<run>` — that pattern assumes a
     non-existent parent→child layout.
   - **Report:** `revrem report "$RUN_DIR" --output revrem-report.html`.
   - **Upload:** when `upload-artifacts` is true, upload `revrem-report.html`
     and, when `raw-artifacts` is **also** true, the full run directory. By
     default (i.e. `raw-artifacts: false`) upload only the redacted HTML
     report, because a raw run directory can contain model output, prompts,
     check output, and local context paths — Contract #4 (redaction on by
     default for anything that leaves the run dir) applies to CI uploads
     equally.
   - **Comment:** when `comment` is true, run `scripts/ci/post_pr_comment.py`.
   - **Exit-code mapping:** `0` pass; `2` findings → configurable (default:
     neutral/soft-fail so the comment is the signal, with an opt-in
     `fail-on-findings: true`); `3/4/5` → fail with a clear message.
2. **Idempotent comment (`post_pr_comment.py`).** Find an existing comment
   authored by the action bot that carries a hidden marker
   (`<!-- revrem-report -->`); update it if present, else create it. Body: status
   badge, finding/suppression counts, cost, top findings (bounded), a "rerun"
   hint, and a link to the uploaded artifact. **Redact** the body using
   `redaction.py` semantics (the script can shell to `revrem report --format
   json` or import the helper if packaged) — never paste raw transcripts.
   Standard library + `urllib` only; no extra deps.
3. **Least privilege.** Document and set `permissions:` to `contents: read`,
   `pull-requests: write`, `issues: write` (for the comment) only. The Action
   never uploads off the repo's CI store (Contract #4, PLAN-003 privacy
   contract).
4. **Boundedness.** The action template always passes a wall-clock and an
   iteration cap; document that omitting them is unsupported in CI.

**Acceptance criteria.**
- Opening a PR on this repo triggers `revrem-pr.yml`; within the 5-minute metric
  target on a ~1k-LOC PR, a single comment appears summarizing findings, cost,
  and suppressions, with an artifact link.
- Re-running the workflow updates the same comment instead of stacking new ones
  (idempotency verified by the marker).
- The job respects budget caps and maps exit codes correctly (a `3` ceiling hit
  fails the job with a budget message, not a generic error).
- `post_pr_comment.py` runs on Python stdlib only and redacts secrets in a
  poisoned-fixture test.

**Tests.**
- `tests/test_post_pr_comment.py`: given a fixture `summary.json` and a fake
  GitHub API (recorded HTTP / a stub server), assert create-vs-update logic,
  marker handling, body redaction, and bounded finding count.
- **Artifact-dir discovery test:** assert that the action step correctly
  extracts the actual run directory from `--summary-format json` output (the
  `artifact_dir` field), not from a hard-coded path. A test using a mock runner
  invocation that writes `artifact_dir` to stdout confirms this.
- **Redacted upload test:** given a fixture run dir containing a synthetic
  secret, assert that the upload step with `raw-artifacts: false` (default)
  does not include the raw `events.jsonl` or model-output files, and that
  `revrem-report.html` has the secret scrubbed by redaction.
- **Raw upload opt-in test:** with `raw-artifacts: true`, assert the full run
  dir is included.
- A workflow-lint / `act`-style or schema check on `action.yml` and the
  workflow YAML (at minimum `yamllint` + a parse test).

**Docs.** New "Hands-off CI" section in `REVREM-DEVEX-001` with the Action usage,
permissions table, GitLab/Buildkite/generic-shell equivalents (the Action is
exemplary, not exclusive), and the privacy contract. README gains a CI badge /
"Use in CI" pointer.

**Cheap-model suitability:** Medium. The comment script and YAML are
template-shaped; the GitHub API stubbing is the main subtlety — provide the fake
in T0 or here.

---

## Task T5 — Expert-profile loader and built-in surface

**Goal.** Let users invoke tuned, bundled profiles by name (`revrem --profile
security`) without writing TOML, while keeping user/project profiles
authoritative when they shadow a built-in.

**Files.**
- New: `src/code_review_loop/expert_profiles/` package containing one TOML per
  profile (`security.toml`, `performance.toml`, `refactor.toml`,
  `test_gap.toml`, `docs.toml`) plus an `__init__.py` loader.
- Edit: `src/code_review_loop/profiles.py` — add a built-in tier to the
  existing resolution chain. The current chain (see `resolve_profile_from_files`
  at `profiles.py:612`) is:
  `user defaults → user named → project defaults → project named → error`.
  The new chain inserts the built-in at the right place so it is overridable:
  `user defaults → builtin named → user named → project defaults → project named → error`.
  Concretely: after applying user defaults, attempt to load the built-in profile
  of the given name and merge it; then apply user named (which shadows the
  built-in), then project defaults and project named (which shadow everything).
  This means a project `.revrem.toml` `[profile.security]` fully overrides the
  built-in; a user `profiles.toml` `[profile.security]` partially overrides
  (after user defaults). If neither user nor project defines the name and no
  built-in matches, raise the existing `FileNotFoundError`. Document this merge
  order explicitly in `REVREM-DEVEX-001`.
- Edit: `pyproject.toml` — add `code_review_loop.expert_profiles` package data
  (`*.toml`) to `[tool.setuptools.package-data]`.
- New (optional): `docs/52-api/schemas/expert-profile-v1.schema.json` +
  `_history` baseline if expert profiles need any manifest fields beyond the
  existing profile schema (e.g. `self_skip_when`, `expected_fixture`). Prefer
  reusing the existing profile schema; only add fields if a profile genuinely
  needs them (e.g. accessibility/perf self-skip), and then additively.

**Implementation steps.**

1. Add a `list_builtin_profiles()` and `load_builtin_profile(name)` to the new
   package; profiles are parsed through the same validator as user profiles so
   they cannot drift from the profile schema.
2. Wire resolution in `profiles.py` so `--profile <name>` falls back to a
   built-in when no user/project profile matches, and `revrem config list`
   shows built-ins with a `source = "builtin"` marker (read-only; `config
   edit`/`delete` refuse to mutate a built-in and instead offer `config clone
   <name> <copy>`).
3. Each built-in profile references a tuned triage rubric and prompt fragments
   (content in T6) and a recommended check matrix; profiles that only apply to a
   subset of repos (e.g. `accessibility`, if added later) declare a self-skip
   marker honored at preflight.

**Acceptance criteria.**
- `revrem --profile security --dry-run` resolves the built-in and previews the
  expected provider commands without a user-authored profile present.
- A user profile named `security` shadows the built-in (verified by a test).
- `revrem config list` shows built-ins as `source = builtin`; `config edit
  security` refuses and suggests `config clone`.
- Built-in profiles validate against the profile schema in CI.

**Tests.** `tests/test_expert_profiles.py`: resolution precedence (four cases:
built-in only, user named shadows built-in, project named shadows built-in,
project named shadows user named shadows built-in), shadowing, read-only
protection, schema validation of every bundled TOML. Tests must exercise the
exact `resolve_profile_from_files` code path, not just the loader helpers.

**Docs.** New "Expert profiles" section in `REVREM-DEVEX-001`; README "Key
Features" mention.

**Cheap-model suitability:** Medium. Touches profile precedence — keep changes
narrow and lean on existing validation.

---

## Task T6 — Expert-profile content (rubrics, fragments, check matrices)

**Goal.** Make each bundled profile a genuinely distinct lens, not a renamed
default.

**Files.**
- Edit: the five TOMLs from T5.
- New prompt fragments under `src/code_review_loop/prompts/fragments/`:
  `performance-checklist.txt`, `refactor-checklist.txt`, `test-gap-checklist.txt`,
  `docs-drift-checklist.txt` (reuse the existing `security-checklist.txt` for
  the security profile). Add their names to the built-in fragment allowlist used
  by `prompts_composer.py` (the same allowlist documented in `REVREM-DEVEX-001`).
- Edit: `pyproject.toml` package-data already covers `prompts/fragments/*.txt`.

**Implementation steps.**

1. For each profile, author (a) a tuned **review framing** / triage rubric
   emphasizing that lens, (b) a **severity policy** (e.g. `refactor` never blocks
   on its own — lower default severity; `security` escalates auth/secrets/PII to
   a non-de-escalatable frontier route, reusing the existing routing policy
   engine), (c) a **recommended check matrix** (e.g. `security` pairs well with
   `pip-audit`/`npm audit`; `test-gap` pairs well with coverage; `performance`
   pairs well with benchmarks) — but these checks must be **advisory only**:
   they appear as documentation and as suggestions from `revrem checks suggest`,
   and are never enabled by default unless `revrem doctor` positively detects
   the relevant tooling in the project. Built-in profiles must not assume
   ecosystem commands are installed. If `pip-audit` is absent the security
   profile must still work; it simply cannot run that check. This avoids
   repeating the pattern where wrong-stack checks fail or produce noise, and (d)
   a pointer to its fixture in the T0 contrived repo.
2. Keep prompts deterministic fragments composed via `prompts_composer.py`; do
   not invent fragment names outside the allowlist (the triage prompt already
   warns models about this).
3. Profiles must be conservative: `docs` and `refactor` default to advisory
   severity; `security` is the only one that escalates by default.

**Profile intents (summary).**
- `security` — vuln classes, secret leakage, unsafe deserialization, authn/authz
  drift, dependency CVE delta.
- `performance` — algorithmic complexity, hot-path allocations, N+1, sync-in-async.
- `refactor` — duplication, dead code, leaky abstractions, naming; never blocks alone.
- `test-gap` — untested branches and recently-changed uncovered code.
- `docs` — drift between code and adjacent docstrings/READMEs.

**Acceptance criteria.**
- Each profile, run against its matching seeded issue in the contrived repo,
  flags that issue (validated in T7).
- `security` escalates a seeded auth/secret finding to the frontier route under
  routing; `refactor` does not block when run alone on a refactor-only diff.
- All referenced fragments resolve (no unresolved-fragment warnings on a clean
  run).
- No built-in profile enables a check command by default unless `doctor`
  detects the corresponding tooling. Verified by a test that runs each profile's
  default check matrix against a bare Python repo with only `git` + `revrem`
  installed and asserts no `command not found` or non-zero check-setup exit.

**Tests.** Covered by T7's suite plus a fragment-resolution unit test.

**Docs.** Document each profile's intent, severity policy, and check matrix in
`REVREM-DEVEX-001`.

**Cheap-model suitability:** Medium. Content authoring; correctness is pinned by
T7's fixtures.

---

## Task T7 — Expert-profile fixture suite and overlap metric

**Goal.** Prove the profiles are distinct (the PLAN-003 M7 success metric: ≥ 4
profiles, ≤ 20% finding overlap on a contrived bug suite) without spending model
calls in CI.

**Files.**
- New: `tests/test_expert_profile_overlap.py`.
- New: `scripts/expert-profile-overlap` (optional dev tool to compute and print
  the overlap matrix from fake-harness runs).
- Reuse: the fake harness (`REVREM_ALLOW_FAKE_HARNESS=1`) and fixtures from T0.

**Implementation steps.**

1. Drive each profile through the **fake harness** against the contrived repo,
   using scripted review/triage outputs per profile so the suite is hermetic and
   deterministic (no Codex, no network) — exactly how existing fake-harness
   contract tests work.
2. Compute pairwise finding-overlap by fingerprint across profiles; assert ≥ 4
   profiles each flag their seeded issue and pairwise overlap ≤ 20%.
3. Provide an optional **live smoke** (gated like the existing
   `REVREM_LIVE_*` tests) that runs the real profiles against the contrived repo
   for maintainers, skipped by default.

**Acceptance criteria.**
- The hermetic overlap test passes in CI with no model/network access.
- The computed overlap matrix is recorded as a test artifact for inspection.

**Tests.** This task *is* the test; also assert each profile self-skips
correctly where it declares a self-skip marker.

**Docs.** `REVREM-TEST-001` gains the overlap gate; `REVREM-DEVEX-001` references
the metric.

**Cheap-model suitability:** Medium. Reuses the fake-harness pattern; the metric
math is simple set arithmetic.

---

## Task T8 — `examples/` matrix

**Goal.** Let a newcomer copy a working profile for their stack in seconds.

**Files.** New `examples/` directory at repo root:
- `examples/python-final-pr/.revrem.toml` + `README.md`
- `examples/typescript/.revrem.toml` + `README.md` (uses `pnpm test`,
  `pnpm run typecheck`, `pnpm run lint`)
- `examples/go-or-rust/.revrem.toml` + `README.md` (pick one; native checks)
- `examples/triage-routing/.revrem.toml` + `README.md`
- `examples/commit-after-remediation/.revrem.toml` + `README.md`
- `examples/ci-hands-off/.revrem.toml` + `README.md` (references the T4 Action)

**Implementation steps.**
1. Each example is a minimal, copy-pasteable profile plus a 10-line README
   describing when to use it and the one command to run.
2. Add a CI lint step that parses every `examples/**/.revrem.toml` through the
   profile validator so examples can never drift from the schema.

**Acceptance criteria.**
- Every example profile validates via `revrem config import`/profile validation
  in CI.
- A newcomer can `cp examples/python-final-pr/.revrem.toml .` in a disposable
  repo and `revrem --profile <name> --dry-run` previews correctly.

**Tests.** `tests/test_examples_valid.py` validates all example profiles.

**Docs.** README "Examples" pointer; `REVREM-DEVEX-001` reference.

**Cheap-model suitability:** High. Mostly content with a validation guard.

---

## Task T9 — Demo recording pipeline + README asset

**Goal.** Replace the scripted demo reconstruction with a *maintained* asset so
the README demo cannot rot.

**Files.**
- New: `scripts/record-demo` (records a deterministic run via the fake harness
  or a fixture and produces an asciicast and/or GIF).
- Edit: `README.md` (swap the hand-written demo block for the generated asset;
  keep the text fallback).
- Assets under `docs/assets/`.

**Implementation steps.**
1. Use the fake harness + a fixed scenario so the recording is reproducible and
   never spends model calls. Produce `docs/assets/revrem-demo.cast` (asciinema)
   and/or a GIF; document the regeneration command.
2. Keep the existing text-version `<details>` fallback in the README for
   environments that do not render the asset.

**Acceptance criteria.**
- `scripts/record-demo` reproduces the asset deterministically from a fixture.
- README references the maintained asset and notes how it was produced.

**Tests.** A smoke test that `scripts/record-demo --check` (dry) runs without a
model and exits `0`.

**Docs.** README; `docs/assets/` note.

**Cheap-model suitability:** Medium. Recording tooling can be fiddly; keep the
fake-harness path the default.

---

## Task T10 — Shell completions (bash/zsh/fish)

**Goal.** Ship completions so power users get tab-completion for subcommands,
flags, and profile names.

**Files.**
- New: `src/code_review_loop/completions/` with generated or hand-maintained
  `revrem.bash`, `revrem.zsh`, `revrem.fish`, plus a generator
  `src/code_review_loop/cli/commands/completions.py` exposing `revrem
  completions {bash,zsh,fish}` that prints the script to stdout.
- Edit: `cli/commands/registry.py` to register `"completions"`.
- Edit: `pyproject.toml` package-data for `completions/*`.

**Implementation steps.**
1. Derive completion data from the existing argparse parsers in `cli/args.py`
   where feasible (subcommand list from the registry; flags from the parsers).
   Profile-name completion can shell to `revrem config list --format json`.
2. Document install: `revrem completions zsh > ~/.zfunc/_revrem` etc.

**Acceptance criteria.**
- `revrem completions bash|zsh|fish` prints a valid completion script and exits
  `0`.
- Subcommands in the registry appear in the generated completion.

**Tests.** `tests/test_completions.py`: each shell target emits non-empty output
and includes a known subcommand (`report`) and flag.

**Docs.** `REVREM-DEVEX-001` install snippet.

**Cheap-model suitability:** High. Bounded, with a clear generation source.

---

## Task T11 — Failure-diagnostics guide + good-first-issues

**Goal.** Close the "diagnose without reading source" loop with a guide derived
from the M2 schema, and seed external contribution.

**Files.**
- New: `docs/70-devex/devex-002-failure-diagnostics-guide.md` (governed).
- Edit: `.github/ISSUE_TEMPLATE/*` to collect version, command, harness,
  artifact path, and failure-summary fingerprint (some may already exist from
  M0 — extend, don't duplicate).
- New: three `good first issue` definitions (as Markdown stubs under
  `docs/05-planning/` or as GitHub issues) with acceptance criteria that do not
  require Codex internals (e.g. "add `fish` completion edge case", "add a
  `migration` expert profile", "add a GitLab CI example").

**Implementation steps.**
1. Map each diagnostic code (from `scripts/dev-render-diagnostics`) and each exit
   code to a "what it means / what to do" entry, cross-referencing
   `summary.json` + `diagnostics.json` fields.
2. Ensure issue templates capture the bug-bundle fingerprint so reports are
   actionable.

**Acceptance criteria.**
- The guide enumerates every current diagnostic code and exit code with a
  remedy, and `meminit check` passes for the new DEVEX doc.
- Issue templates collect the required fields.
- ≥ 3 starter issues exist with crisp acceptance criteria.

**Tests.** A doc test asserting the guide's diagnostic-code table matches
`scripts/dev-render-diagnostics` output (no drift).

**Docs.** This task is largely docs; link the guide from README and
`REVREM-DEVEX-001`.

**Cheap-model suitability:** High. Structured writing from existing tables.

---

## Task T12 (STRETCH) — TUI starts real runs

**Goal.** Let the Textual UI launch, monitor, cancel, and summarize real runs —
the final open slice of PLAN-003 M5 — *without* creating a second execution
engine.

**Files.**
- Edit: `src/code_review_loop/tui.py`, `tui_state.py`.
- Reuse: `application.py` (the headless application boundary) and the
  `RendererSink` event adapter already in `events.py`.

**Implementation steps.**
1. The TUI's "run" action calls the **same application boundary** the CLI uses,
   passing a `RendererSink` whose callback updates the Run Monitor view from
   `Event`s. No review/remediation logic is reimplemented in the TUI
   (import-linter already forbids `tui` from importing `runner`/`cli`).
2. Implement cancellation through the existing cancellation path (emits
   `cancellation`, writes artifacts, exits code `5`), surfaced as a TUI control
   and verified with Textual Pilot tests.
3. Gate behind the `tui` extra and an explicit "experimental" notice; until
   Pilot coverage is solid, keep the **replay-from-events** rendering as the
   default and the live run behind a flag.

**Acceptance criteria.**
- A TUI-launched run produces the **same** `summary.json` and artifacts as the
  equivalent CLI run on the same fixture/repo.
- Pilot tests cover launch, cancellation, cost-ceiling, and ≥ 3 failure states.
- No new execution path: `lint-imports` stays green; the engine is unchanged.

**Tests.** Textual Pilot tests (dependency-gated like existing TUI tests) +
an equivalence test (TUI run vs CLI run artifacts).

**Docs.** Update `REVREM-PLAN-002` (TUI run deferral) to record this slice
landing; `REVREM-DEVEX-001` TUI section.

**Cheap-model suitability:** Low. Highest-risk task; recommend a stronger model
or human pairing. **Defer to v0.6.0 if capacity is tight** — it does not gate the
showcase.

---

## Task T13 — Release: version bump, CHANGELOG, schema-freeze notes, tag

**Goal.** Cut v0.5.0 cleanly under the existing release contract
(`REVREM-ADR-011`, `REVREM-RUNBOOK-001`).

**Implementation steps.**
1. Bump version to `0.5.0` in `pyproject.toml` and
   `src/code_review_loop/__init__.py` (the release workflow refuses to publish
   if tag, `pyproject`, and `__init__` disagree).
2. Update `CHANGELOG.md` `[Unreleased]` → `[0.5.0]` with Added/Changed/Fixed
   sections covering report, Action, expert profiles, DevEx, and (if landed)
   TUI runs.
3. Add a **stability note** matching PLAN-003's 0.5.0 boundary: artifact schema
   v1 and suppressions format remain frozen; `summary.json`/`events.jsonl`
   changes stay additive; the HTML report layout is explicitly *not* a stable
   contract yet. Record the expert-profile surface as Preview.
4. Update `REVREM-DEVEX-001` Version History; run the full gate
   (`./scripts/dev-check`, `pre-commit run --all-files`, `meminit check --format
   json`, `git diff --check`), then dry-run the release workflow before tagging
   `v0.5.0`.
5. Dogfood: run `revrem --profile dogfood` (and the new `revrem report` on the
   resulting run dir) on this PR before tagging.

**Acceptance criteria.**
- Versions agree across `pyproject.toml`, `__init__.py`, and the `v0.5.0` tag.
- CHANGELOG and stability notes are complete; release dry run is green.
- `revrem report` renders the release dogfood run.

**Cheap-model suitability:** High (mechanical), but gated on all committed tasks.

---

## Minimum Release Core (Recommended Sequencing)

If capacity is limited, the minimum releasable core is **T0 + T1 + T2 + T3 + T4 + T13**
(Pillars A and B). This proves the report and CI surfaces from existing artifacts,
closes PLAN-003 M8, and produces the "screenshot-worthy showcase" goal. Expert
profiles (T5–T7) and DevEx expansion (T8–T11) can land as follow-on PRs or in a
v0.5.x patch once the CI surface is validated. T12 (TUI runs) should be explicitly
deferred to v0.6.0 unless a dedicated pairing session is available. The release
exit criteria below cover all committed pillars; adjust the CHANGELOG accordingly
if any pillar is deferred.

## Release & Exit Criteria

v0.5.0 is releasable when **all committed pillars (A–D)** meet their acceptance
criteria and:

- `./scripts/dev-check`, `pre-commit run --all-files`, `meminit check --format
  json`, and `git diff --check` pass; `lint-imports` is green (no new boundary
  violations).
- `revrem report` renders every T0 fixture deterministically and validates its
  inputs against `summary-v1`/`events-v1` schemas; no model/network access.
- The reference GitHub Action posts a single idempotent PR comment within the
  5-minute metric on a ~1k-LOC PR and respects budget ceilings.
- ≥ 4 expert profiles flag their seeded issues with ≤ 20% pairwise overlap on
  the contrived repo, hermetically (fake harness, no network).
- Examples validate in CI; completions emit for all three shells; the demo asset
  regenerates from a fixture; the failure-diagnostics guide has no code drift.
- The GitHub Action correctly discovers the actual run directory from runner
  output (not from a hard-coded path); artifact-dir discovery test passes.
- CI uploads default to the redacted HTML report only; raw run-dir upload
  requires explicit `raw-artifacts: true`; redacted-upload test passes.
- Built-in profile precedence integration test passes all four shadowing cases.
- No built-in profile enables an ecosystem check command unless `doctor`
  positively detects it; stack-detection test passes.
- At least one live dogfood run of `revrem --profile dogfood` (CLI) on a real
  branch, with `revrem report` rendering the result, is recorded before tagging.
- Pillar E (TUI runs) either meets its acceptance criteria *or* is explicitly
  deferred to v0.6.0 in the CHANGELOG — it does not block the release.

## Mapping To The Path-To-1.0

This plan advances PLAN-003 as follows. After v0.5.0, the only remaining roadmap
work is the final M5 TUI slice (if deferred here) and **M9** (archive, dataset
export, daemon) — the natural v0.6.0/0.7.0 focus, leading to the 1.0 "boring
infrastructure" freeze.

| PLAN-003 milestone | Status after v0.5.0 |
|---|---|
| M0–M4, M6 | Done (v0.4.0) |
| M5 (TUI runs, hooks, headless) | Hooks/headless done; TUI real runs done **or** deferred (Pillar E) |
| M7 (expert profiles + DevEx) | **Done** (Pillars C, D) |
| M8 (CI surface + HTML report) | **Done** (Pillars A, B) |
| M9 (archive, daemon, dataset) | Next (v0.6.0+) |

## Open Questions

- **OQ-A (T4).** Action in this repo (`action.yml` at root) vs. a sibling
  marketplace repo? PLAN-003 OQ5 leans "own repo for marketplace, this repo for
  fewer moving parts." Recommendation: ship in-repo for v0.5.0; extract later if
  a marketplace listing is wanted.
- **OQ-B (T5/T6).** Do any expert profiles need manifest fields beyond the
  current profile schema (e.g. `self_skip_when`, `expected_fixture`)? If yes,
  add them additively with a new `expert-profile-v1` schema + history baseline;
  if no, reuse the existing profile schema.
- **OQ-C (T2).** Does the report need a `--format json` index beyond the HTML, or
  is HTML + the existing `summary.json` sufficient for CI? Default: provide the
  small JSON index (cheap, useful for the Action).
- **OQ-D (Pillar E).** Commit Pillar E to v0.5.0 or pre-commit to deferring it to
  v0.6.0 to protect the release date? Recommendation: treat as stretch; decide at
  the T0/T1 review gate based on capacity.
