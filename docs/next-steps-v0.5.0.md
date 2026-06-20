---
document_id: REVREM-PLAN-005
type: PLAN
title: Next steps — v0.5.0 (Showcase & Hands-Off Adoption)
status: Draft
version: '0.1'
last_updated: '2026-06-20'
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

v0.5.0 ships five pillars across two release tiers. **Pillars A and B are the
committed minimum core (Tier 1)**; the release is gated on these alone. Pillars
C and D are the full candidate scope (Tier 2) and land as follow-on v0.5.x
releases if capacity allows — they are not required to cut v0.5.0. Pillar E is
a stretch that may slip to v0.6.0 without blocking the release. See the Release
& Exit Criteria section for precise gate conditions for each tier.

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

| Capability | Tier | Target maturity at v0.5.0 |
|---|---|---|
| `revrem report` HTML | Tier 1 (committed) | Default-on for local use (documented, schema-validated inputs, fixture-tested) |
| GitHub Action + PR comment | Tier 1 (committed) | Preview (documented, reference repo smoke, least-privilege tokens) |
| Expert profiles | Tier 2 (v0.5.x follow-on if capacity limited) | Preview (documented, fixture suite proves distinct findings; not yet SemVer-frozen) |
| Examples / completions / demo | Tier 2 (v0.5.x follow-on if capacity limited) | Default-on for local use |
| TUI real runs (stretch) | Tier 1 stretch / v0.6.0 | Experimental (flagged; Pilot-tested replay before live runs) |

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
   must be created or registered via Meminit). Update the Meminit index (the
   in-repo governed document index that `meminit check` reads) accordingly.
   Confirm `meminit check --format json` passes with the
   front-matter above (document_id `REVREM-PLAN-005`). This is the very first
   action in T0 because downstream tasks reference this document's stable path.
2. Create a **finished-run fixture catalogue** under
   `tests/fixtures/runs/` (reuse the existing golden artifact scenarios). Ensure
   each scenario directory contains a valid `summary.json` and `events.jsonl`
   for at least: `clear`, `findings_remediated`, `findings_remaining`,
   `timeout`, `check_failure`, `cost_ceiling`, `cancelled`, and
   `all_suppressed`. Add a small loader helper `tests/support/run_fixtures.py`
   exposing `load_run(name) -> Path` so T1/T2/T4 share inputs.
3. *(Tier 2 only — skip for Tier 1 release.)* Create the **contrived
   multi-issue reference repo** fixture under `tests/fixtures/expert_repo/`
   (or extend the existing reference fixture repository noted in the v0.4.0
   changelog). It must contain seeded issues that map to each expert profile:
   at least one security bug (e.g. unsafe deserialization / hardcoded secret),
   one performance bug (e.g. an N+1 / hot allocation), one refactor smell
   (duplication / dead code), one test gap (changed-but-uncovered branch), and
   one docs drift (docstring contradicts code). Record expected-flag metadata in
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
- *(Tier 2 only)* `tests/fixtures/expert_repo/EXPECTED.json` enumerates ≥ 5
  seeded issues with the profile expected to flag each.

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
   emit a machine index instead of HTML — at minimum: `schema_version`, run id,
   final status, finding counts (by severity), suppression count, **cost_usd**,
   **top_findings** (list of at most 5 redacted finding summaries: severity,
   file, line, one-sentence title), and artifact paths. These fields are
   the minimum required for `post_pr_comment.py` to populate the PR comment
   body from this file alone, without reading raw `events.jsonl` or
   `summary.json`. Apply redaction to all rendered text when `redact` is true
   (default) — this makes the JSON index safe to upload or pass across a trust
   boundary.

   **Field nullability contract** (all consumers must handle these):
   - `cost_usd`: `null` if the run was a dry-run or the engine did not record a
     cost (e.g. fake harness); never absent from the key set.
   - `top_findings`: `[]` (empty list) when there are no findings or they were
     suppressed; each entry's `line` field is `null` when the finding has no
     file-level location.
   - `artifact_paths`: `{}` (empty object) if the run dir is unavailable or was
     not written (e.g. `--dry-run`); otherwise a dict keyed by artifact type
     (`"summary"`, `"events"`, `"report_html"`).
   - All other required fields (`schema_version`, `run_id`, `final_status`,
     finding counts, `suppression_count`) are always present and non-null; a
     missing key is a schema violation, not a null.
   Add a golden fixture (`tests/fixtures/report_index_golden.json`) that
   `test_report_json.py` asserts byte-for-byte (modulo run-id/timestamps
   masked with a normaliser) so schema drift is caught immediately. Per
   Contract #8, also add `docs/52-api/schemas/report-index-v1.schema.json`
   (a JSON Schema file describing all fields, types, and nullability) plus an
   `_history/` baseline, and validate the golden fixture against the schema in
   `test_report_json.py`. The Action consumes this artifact, so the schema is
   a versioned cross-boundary contract.
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
- `revrem report <run-dir> --format json` prints canonical JSON to stdout
  with a `schema_version`. When `--format json`, the `--output` flag is
  ignored; use a shell redirect (`> file.json`) to write to a file.
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
- `tests/test_report_json.py`: for each T0 fixture, `revrem report --format
  json` produces valid JSON on stdout; assert `schema_version`, `run_id`, and
  required keys are present and match the golden fixture
  (`tests/golden/report/report-index-*.json`). Validate each golden against
  `docs/52-api/schemas/report-index-v1.schema.json`. Assert `--output` flag is
  silently ignored when `--format json` (output still lands on stdout, not a
  file).

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
  `src/code_review_loop/adapters/terminal.py` (terminal-title / control-sequence
  writes — see step 1 note below), `src/code_review_loop/cli/args.py` (flag),
  `cli/outcome.py`/`cli/exit.py` (verify code mapping), and `reporting.py` if
  a stdout JSON summary needs a stable shape.

**Implementation steps.**

1. **Implement `--no-tty` and `CI=true` auto-detection in `progress.py`.**
   The goal is that RevRem never emits ANSI escape sequences (colour codes,
   cursor movement, terminal-title writes, progress spinners) in any headless
   context. Two complementary mechanisms achieve this:

   - **Auto-detect `CI=true`.** Most CI providers (GitHub Actions, CircleCI,
     Travis, Jenkins) set the environment variable `CI=true` automatically —
     no user action required. In `progress.py`, extend the `force_terminal`
     calculation to also check this variable: when `CI` is set, treat the
     session as non-interactive regardless of `isatty()`. This is the
     zero-friction path: a standard CI run requires no RevRem-specific flags.

   - **Add `--no-tty` flag.** Some CI environments do not set `CI`, and
     developers sometimes want headless output locally (e.g. piping to a
     file while their terminal is still attached). Add `--no-tty` to
     `cli/args.py` (boolean flag, no value); when set, force non-interactive
     mode regardless of `isatty()` or `CI`. Wire it through
     `build_loop_config` to the progress layer.

   The combined gate in `progress.py`:
   ```python
   force_terminal = (
       sys.stderr.isatty()
       and not os.environ.get("CI")
       and not config.no_tty
   )
   ```

   When `force_terminal` is False, suppress everything that produces ANSI:
   Rich progress, terminal-title writes (`\033]0;...\007`), and any other
   escape sequences not routed through Rich. Emit stable, greppable,
   line-oriented log lines via `--progress-style compact` in this mode.
   Document `--progress-style compact` as the recommended CI setting in
   `REVREM-DEVEX-001`.

   > **`adapters/terminal.py` also needs updating.** `terminal_title_supported()`
   > in that file checks `sys.stderr.isatty() or Path("/dev/tty").exists()`.
   > On many CI runners `/dev/tty` exists even when `stderr` is redirected —
   > so even if `progress.py`'s gate is False, terminal-title sequences could
   > still reach `/dev/tty`. Extend `terminal_title_supported()` to also
   > check `config.no_tty` and `os.environ.get("CI")`:
   > `return config.terminal_title and not config.no_tty and not os.environ.get("CI") and (sys.stderr.isatty() or ...)`.
   > This must be in scope for T3 — tests that capture `stderr` alone will
   > not catch `/dev/tty` writes. The T3 test suite must monkeypatch
   > `write_terminal_control_to_tty` and assert it is never called under
   > `--no-tty` or `CI=true`.

   > **Why two mechanisms?** A single `--no-tty` flag requires every CI
   > workflow YAML to include it explicitly — easy to forget. A single env-var
   > check means a developer running a local script cannot force headless mode
   > without setting environment variables — clunky. Both together cover all
   > cases while keeping the CI YAML minimal.
2. Guarantee the documented exit codes (Contract #6) are emitted on every
   terminal path in headless mode, including `3` (ceiling), `4` (setup/resume),
   `5` (cancel). Add a parametrized test mapping each scenario fixture to its
   exit code.
3. Provide a **machine run-summary on stdout** suitable for CI logs:
   `--summary-format json` already exists; verify it prints canonical
   `summary.json` content and add a `--summary-format both` ordering test
   (text block first, then a blank line, then the JSON block) so the documented
   ordering is contractually verified. **Note:** `both` is useful in interactive
   scripts where a developer wants readable output *and* wants to pipe JSON to
   `jq`. In the T4 GitHub Action, always use `--summary-format json` — `both`
   prepends text before the JSON and breaks stdout-as-JSON-stream parsing
   (see T4 step 1, Run).
4. Ensure `events.jsonl` and `summary.json` are always written before process
   exit on every terminal path (already true for most; add coverage for the
   headless cancel path).

**Acceptance criteria.**
- With `--no-tty` set, **stderr** contains zero ANSI escape bytes and is
  greppable line-by-line. (ANSI progress output goes to stderr, not stdout —
  Rich writes to `sys.stderr`; the test must capture stderr, not stdout.)
- With `CI=true` in the environment and no explicit flags, the same ANSI-free
  behaviour is observed on stderr — confirming auto-detection fires.
- Each scenario fixture exits with its documented code when run with `--no-tty`.
- `--summary-format json` output validates against `summary-v1.schema.json`.

**Tests.** `tests/test_headless_output.py` (all scenarios use
`REVREM_ALLOW_FAKE_HARNESS=1` for hermetic, model-free execution):
- **ANSI-free on stderr via `--no-tty`**: run each scenario with `--no-tty`
  and assert stderr contains zero bytes matching the ANSI escape pattern
  `\x1b\[`. Capturing stdout separately to confirm JSON output is clean.
- **ANSI-free via `CI=true`**: same assertion but without `--no-tty`,
  using `CI=true` in the subprocess environment — this confirms
  auto-detection fires independently of the explicit flag.
- **Exit-code matrix**: parametrized across scenario fixtures, asserting
  each maps to its documented code (Contract #6).
- **JSON summary validation**: `--summary-format json` output validates
  against `summary-v1.schema.json`.

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
- New: `action.yml` (composite action at repo root — see D-1).
- New: `.github/workflows/revrem-pr.yml` — a reference workflow that uses the
  action on this repo's own PRs (dogfood).
- New: `scripts/ci/post_pr_comment.py` — a small, dependency-light script that
  reads `revrem-report.json` (the redacted JSON index written by the Report step)
  and posts/updates one PR comment via the GitHub REST API using `GITHUB_TOKEN`.
  Its full input surface: `revrem-report.json` on disk; env vars read from the
  GitHub Actions runtime (all automatically set by Actions, none need to be
  explicitly forwarded unless overriding):
  - `GITHUB_TOKEN` — authentication for the REST API comment calls
  - `GITHUB_REPOSITORY` — `owner/repo` string for the API URL path
  - `GITHUB_EVENT_PATH` — path to the event JSON; the script reads
    `.pull_request.number` from it to identify the target PR
  - `GITHUB_API_URL` — base URL (defaults to `https://api.github.com`; allows
    GitHub Enterprise Server support without code changes)
  - `REVREM_ARTIFACT_URL` — artifact deep-link or workflow run URL fallback,
    set by the Action before invoking the script; the script never constructs
    artifact URLs itself
- New: `docs/52-api/` note or `REVREM-DEVEX-001` section documenting the Action
  contract and least-privilege permissions.

**Implementation steps.**

1. **Composite action (`action.yml`).** Inputs: `base` (default `origin/main`),
   `profile`, `max-iterations`, `max-wall-seconds`, `max-usd`, `max-tokens`,
   `checks` (newline list), `comment` (bool, default true),
   `upload-artifacts` (bool, default true), `raw-artifacts` (bool, default
   false — see artifact upload note below), `fail-on-findings` (bool, default
   false — when true, the job exits 1 if revrem returns exit code 2; when
   false, findings are surfaced as a `::warning::` annotation and the job
   passes), `install-mode` (`pypi` or `local`, default `pypi` — see dogfood
   note below). Steps:
   - **Install:** when `install-mode == pypi`, install via
     `pipx install revrem==<version>` where `<version>` is the literal
     version string embedded in `action.yml` (updated by the T13 release task
     to match the tag being cut); when `install-mode == local`, run
     `pip install -e "${{ github.action_path }}"` against the action repo's
     checkout. (`pip install -e .` would resolve to `$GITHUB_WORKSPACE`, which
     is the caller's repo, not the action directory; the `github.action_path`
     prefix is required for portability.) The dogfood workflow uses `local`
     so v0.5.0 can be validated before its PyPI package exists.
     Document both modes clearly.
   - **Checkout contract.** The composite action does **not** call
     `actions/checkout` — that is the caller workflow's responsibility. However,
     RevRem requires the base ref to be present locally for `git diff`. The
     dogfood `revrem-pr.yml` must use `fetch-depth: 0` (full history) or at
     minimum fetch the base branch explicitly:
     ```yaml
     - uses: actions/checkout@v4
       with:
         fetch-depth: 0   # required so origin/main is available for git diff
     ```
     Document this as a caller prerequisite in the Action's README and in
     `REVREM-DEVEX-001`. The action itself should verify the base ref exists
     before invoking RevRem (e.g. `git rev-parse --verify "$base"`) and exit 4
     with a human-readable message if it does not, rather than letting RevRem
     fail with a cryptic git error.
   - **Run:** `revrem --base "$base" --profile "$profile" --no-tty
     --progress-style compact --summary-format json
     --max-iterations ... --max-wall-seconds ... --max-usd ...`.
     The `checks` input (newline-delimited list) must be split into repeated
     `--check <cmd>` arguments; do this in a bash step with
     `while IFS= read -r line; do [[ -n "$line" ]] && args+=(--check "$line"); done <<< "$checks"`.
     Pass the resulting `"${args[@]}"` array to `revrem`. Never interpolate
     the newline-joined string directly into the command — that is a shell
     injection vector. Add a test confirming that a two-entry `checks` input
     produces two separate `--check` flags in the revrem invocation.
     GitHub Actions sets `CI=true` automatically, so RevRem would suppress
     ANSI even without `--no-tty`; the flag is included explicitly so the
     intent is readable in the workflow YAML and the behaviour is guaranteed
     even on non-standard CI providers that omit `CI`. `--progress-style
     compact` produces greppable, line-by-line progress in `revrem-err.txt`
     that operators can read after a failure.
     **Do not pass `--artifact-dir`**: the runner generates a
     timestamped concrete run directory under `.revrem/runs/` by default
     (see `default_artifact_dir()` in `cli/config_builder.py`). Use `set +e`
     (or the composite action equivalent `continue-on-error: true`) so a
     non-zero exit code does not abort the step before later steps can read
     the artifacts. Capture stdout, stderr, and the exit code explicitly:
     `revrem ... > revrem-out.json 2>revrem-err.txt; REVREM_EXIT=$?`.
     **stdout must be pure JSON here — never use `--summary-format both`.**
     `both` prepends a human-readable terminal summary before the JSON block,
     which breaks `jq .artifact_dir` and any other JSON parser reading stdout.
     `--summary-format json` produces a single, valid JSON object and nothing
     else. After capture, **validate that `revrem-out.json` parses as JSON
     before extracting `artifact_dir`**: if the file is empty or not valid JSON
     (e.g. revrem crashed before writing its summary), take the setup-error
     fast-fail path immediately — the same path used when `artifact_dir` is
     absent from valid JSON. This two-stage guard (parse check first, field
     check second) prevents confusing downstream errors if revrem never reached
     the summary-writing stage. Do not fall back to globbing `.revrem/runs/`
     for the newest entry, as that is fragile in CI retries, matrix jobs, and
     reused workspaces.
   - **Report:** Run two report commands in sequence:
     ```
     revrem report "$RUN_DIR" --output revrem-report.html
     revrem report "$RUN_DIR" --format json > revrem-report.json
     ```
     The first produces the HTML report for upload. The second produces the
     machine-readable JSON index (defined in T1 step 3 / D-3) that
     `post_pr_comment.py` reads to build the PR comment body. Both use the
     same `--no-redact` default (redaction on) so neither leaks raw model
     content. The `--format json` flag prints to stdout; redirect to file with
     `>`. Do not use a non-existent `--output-json` flag.
   - **Upload:** when `upload-artifacts` is true, upload `revrem-report.html`
     and, when `raw-artifacts` is **also** true, the full run directory. By
     default (i.e. `raw-artifacts: false`) upload only the redacted HTML
     report, because a raw run directory can contain model output, prompts,
     check output, and local context paths — Contract #4 (redaction on by
     default for anything that leaves the run dir) applies to CI uploads
     equally. Capture the `artifact-url` output from `actions/upload-artifact`
     (available as `steps.<upload-step-id>.outputs.artifact-url`); set it as
     the environment variable `REVREM_ARTIFACT_URL` before invoking
     `post_pr_comment.py`. If upload is skipped or the output is empty, set
     `REVREM_ARTIFACT_URL` to the workflow run URL instead
     (`${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}`
     ) as a fallback so the comment always contains a navigable link. The
     script reads the URL from `REVREM_ARTIFACT_URL`; it does not attempt to
     construct or guess artifact URLs itself.
   - **Comment:** when `comment` is true, run
     `python "${{ github.action_path }}/scripts/ci/post_pr_comment.py"`.
     **Why `${{ github.action_path }}`?** When a user writes
     `uses: owner/revrem@v0.5.0` in their workflow, GitHub checks out the
     *action* repository into a temporary directory, not the caller's workspace.
     The caller's workspace will not contain `scripts/ci/post_pr_comment.py` —
     only the action's own checkout will. `${{ github.action_path }}` always
     points to the directory containing `action.yml`, regardless of which
     repository is being reviewed. Omitting this prefix would cause the step
     to fail immediately with "file not found" for every external user while
     passing in the dogfood workflow (because the dogfood workflow uses
     `install-mode: local` and the script happens to be on disk).
   - **Always render, upload, and comment when `$RUN_DIR` was discovered**,
     regardless of `$REVREM_EXIT`. The report and PR comment are the core value
     of the Action — they must appear even when findings or a budget ceiling
     stopped the run.
   - **Apply the mapped job result last**, after comment/upload complete:
     - `$REVREM_EXIT 0` → exit 0 (job passes).
     - `$REVREM_EXIT 2` (findings): if `fail-on-findings: true` → exit 1 (job
       fails); otherwise → exit 0 (job passes) **and** emit a GitHub Actions
       warning annotation (`echo "::warning::RevRem found N findings — see PR
       comment for details"`) so findings are surfaced on a passing job without
       blocking the merge. GitHub Actions composite actions do not have a native
       "neutral" state; the `::warning::` annotation is the correct substitute.
     - `$REVREM_EXIT 3` (budget ceiling) → exit 1 with a human-readable message:
       "RevRem budget ceiling reached — partial review uploaded. Increase
       max-usd or max-iterations to complete the review."
     - `$REVREM_EXIT 4` (setup/resume) or `5` (cancelled) → exit 1 with a
       clear message derived from `revrem-err.txt`.
     - Any other non-zero → exit 1, attach `revrem-err.txt` to the job summary.
2. **Idempotent comment (`post_pr_comment.py`).** Find an existing comment
   authored by the action bot that carries a hidden marker
   (`<!-- revrem-report -->`); update it if present, else create it. Body: status
   badge, finding/suppression counts, cost, top findings (bounded), a "rerun"
   hint, and a link to the uploaded artifact. **Source the comment body from
   `revrem-report.json`**, the JSON index produced by the preceding Report step
   (`revrem report "$RUN_DIR" --format json > revrem-report.json` — see T1
   step 3 / D-3). This file is written to disk before `post_pr_comment.py` runs
   and is already redacted by `revrem report` (Contract #4, T1), so the comment
   script needs only a plain `json.load()` — no package import. This matters
   because `post_pr_comment.py` lives in `scripts/`, which is not part of the
   wheel; under the default `install-mode: pypi` (`pipx install revrem`),
   `code_review_loop` runs in an isolated virtualenv and is unreachable from a
   loose script. Reading a file on disk works identically under every install
   mode. Never paste raw model output or prompt content into the comment body;
   the JSON index enforces this by design — it contains only summary fields,
   not raw model responses. Standard library + `urllib` only for the HTTP calls;
   no extra deps. If `revrem report --format json` exits non-zero (rare, since
   T1 step 4 makes it resilient to truncated events), post a degraded comment
   with a generic message ("RevRem report generation failed — see workflow
   logs for details") and exit 1. Do **not** include raw stderr in the comment
   body; it may contain file paths or exception tracebacks. If
   `raw-artifacts: true`, upload the captured stderr as a separate artifact
   for diagnosis.
3. **Least privilege.** Composite actions cannot declare `permissions:` — that
   block belongs in the **caller's workflow**, not in `action.yml`. The dogfood
   `revrem-pr.yml` must include:
   ```yaml
   permissions:
     contents: read
     pull-requests: write
   ```
   Document the required permissions in the Action README and in
   `REVREM-DEVEX-001` so public callers know what to add. The Action never
   uploads off the repo's CI store (Contract #4, PLAN-003 privacy contract).

   > **Fork-PR security model (required decision — D-6).** On PRs from forks,
   > GitHub Actions does not grant `pull-requests: write` to the `GITHUB_TOKEN`
   > under the default `pull_request` trigger. Attempting to post a comment will
   > fail silently or with an HTTP 403. The safe behavior for v0.5.0 is:
   > **detect fork and skip the comment step**, but still run `revrem`,
   > generate the report, and upload the artifact so the review is available via
   > the Actions tab. Skip the step entirely via an `if:` condition on the
   > comment step in `action.yml` —
   > `if: inputs.comment == 'true' && github.event.pull_request.head.repo.fork != 'true'`
   > — rather than passing a flag to `post_pr_comment.py`; the simpler model is
   > to never invoke the script when posting is not possible. Do **not** use
   > `pull_request_target` to gain write access on fork PRs — it runs workflow
   > code from the default branch against fork code and requires explicit checkout
   > hardening that is out of scope for v0.5.0. Add a test asserting that fork
   > mode produces an artifact but no comment API call.
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
- `post_pr_comment.py` runs on Python stdlib only. It does **not** redact —
  it reads the already-redacted `revrem-report.json`. A poisoned-fixture test
  confirms no raw secret appears in the posted comment body, because `revrem
  report` (upstream) has already scrubbed it before the script ever runs.

**Tests.**
- `tests/test_post_pr_comment.py`: given a fixture `revrem-report.json` (a
  pre-built JSON index, not raw `summary.json`) and a fake GitHub API
  (recorded HTTP / a stub server), assert create-vs-update logic, marker
  handling, bounded finding count, and that no raw model output appears in
  the posted body (redaction is upstream in `revrem report`, not here).
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
- **Comment-before-fail test:** with `fail-on-findings: true` and a fixture
  that has findings, assert that (a) the PR comment is posted and (b) the
  artifact is uploaded *before* the job exits non-zero. This is the most
  important integration property of the Action: the report must appear even
  when the job fails. Implement using the stub GitHub API and a scripted
  action step invocation; verify ordering by recording the sequence of API
  calls made.
- **Budget-exit message test:** with a fixture that exits `3` (cost ceiling),
  assert that the action emits a human-readable "budget ceiling reached"
  message (not a generic "step failed" error) and that the job result is
  `failure` with the budget exit code surfaced. This verifies that exit-code
  mapping (Contract #6) is wired end-to-end through the action, not just in
  the CLI.
- **Missing-RUN_DIR fast-fail test:** simulate revrem crashing before writing
  `summary.json` (so `artifact_dir` is absent from stdout). Assert the action
  step fails immediately with a "setup error — could not discover run
  directory" message, and does NOT attempt to run the report, upload, or
  comment steps. This guards against silent failures where an empty or missing
  `artifact_dir` would cause the subsequent steps to fail with confusing errors.
- A workflow-lint / `act`-style or schema check on `action.yml` and the
  workflow YAML (at minimum `yamllint` + a parse test).

**Docs.** New "Hands-off CI" section in `REVREM-DEVEX-001` with the Action usage,
permissions table, GitLab/Buildkite/generic-shell equivalents (the Action is
exemplary, not exclusive), and the privacy contract. README gains a CI badge /
"Use in CI" pointer.

**Cheap-model suitability:** Medium. The comment script and YAML are
template-shaped; the GitHub API stubbing is the main subtlety — provide the fake
in T4 as `tests/support/fake_github_api.py` (a minimal `http.server`-based stub
or `responses`-style recorded fixture that handles `GET /repos/.../issues/comments`
and `POST /repos/.../issues/<pr>/comments`).

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
  This means a project `.revrem.toml` `[profiles.security]` fully overrides the
  built-in; a user `profiles.toml` `[profiles.security]` partially overrides
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

1. Add `list_builtin_profiles() -> list[str]` and
   `load_builtin_profile(name: str) -> str` (returns raw TOML text) to the
   new package. **Use `importlib.resources.files()` to read the TOML files,
   not `Path(__file__).parent`.** Here is why this matters: when Python
   installs a package from PyPI into a user's environment, it may store the
   package files inside a zip archive (a "wheel") rather than on disk as
   loose files. `Path(__file__).parent / "security.toml"` only works when
   the files are loose on disk; `importlib.resources` works in both cases.

   ```python
   from importlib.resources import files

   _data = files("code_review_loop.expert_profiles")

   def load_builtin_profile(name: str) -> str:
       return (_data / f"{name}.toml").read_text(encoding="utf-8")

   def list_builtin_profiles() -> list[str]:
       return [
           r.name.removesuffix(".toml")
           for r in _data.iterdir()
           if r.name.endswith(".toml")
       ]
   ```

   Parse the returned TOML text through the same profile validator as user
   profiles so built-in TOMLs cannot silently drift from the profile schema.
   **Do not raise at import time.** If `code_review_loop.profiles` raises
   during import because a built-in TOML is malformed, the *entire CLI fails
   to start* — even commands that don't use profiles. Instead: validate each
   built-in TOML inside `load_builtin_profile()` (at load time, when the
   profile is actually requested) and raise a normal `ValueError` with a clear
   message. Separately, add a packaging test (`tests/test_builtin_profiles.py`)
   that calls `load_builtin_profile(name)` for every name in
   `list_builtin_profiles()` — this catches malformed TOMLs immediately in CI
   without the operator-UX cost of a broken import.
2. Wire resolution in `profiles.py` so `--profile <name>` falls back to a
   built-in when no user/project profile matches, and `revrem config list`
   shows built-ins with a `source = "builtin"` marker (read-only; `config
   edit`/`delete` on a built-in name print an explicit "built-in profile
   '<name>' is read-only; use `revrem config clone <name> <copy>` to create
   an editable copy" error to stderr and exit 1 — they do **not** return a
   generic "not found" error, which would be misleading given the profile is
   discoverable via `config list`).
3. Each built-in profile references a tuned triage rubric and prompt fragments
   (content in T6) and a recommended check matrix; profiles that only apply to a
   subset of repos (e.g. `accessibility`, if added later) declare a self-skip
   marker honored at preflight.

**Acceptance criteria.**
- `revrem --profile security --dry-run` resolves the built-in and previews the
  expected provider commands without a user-authored profile present.
- A user profile named `security` shadows the built-in (verified by a test).
- `revrem config list` shows built-ins as `source = builtin`; `config edit
  security` and `config delete security` exit 1 with the message "built-in
  profile 'security' is read-only; use `revrem config clone security <copy>`
  to create an editable copy" (not a generic "not found" error).
- Built-in profiles validate against the profile schema in CI.

**Tests.** `tests/test_expert_profiles.py`: resolution precedence (four cases:
built-in only, user named shadows built-in, project named shadows built-in,
project named shadows user named shadows built-in), shadowing, read-only
protection (assert `config edit <builtin>` and `config delete <builtin>` each
exit 1 with the exact read-only message, not a "not found" error), schema
validation of every bundled TOML. Tests must exercise the exact
`resolve_profile_from_files` code path, not just the loader helpers.

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
   engine), (c) a **recommended check matrix** — but built-in profiles **ship
   with no ecosystem-specific executable checks enabled by default**. Each
   profile's `pipeline.checks` list in its TOML is empty or contains only
   universally available commands (e.g. `git diff`). In TOML, this is written
   as `checks = []` under a `[pipeline]` section — there is no `[checks]` table
   in the profile schema. Recommended ecosystem checks
   (e.g. `pip-audit`, `npm audit`, `pytest --coverage`) are listed in
   documentation and surfaced as post-install hints by `revrem checks suggest`,
   which already performs stack detection. There is no new dynamic resolution
   path in v0.5.0; the static TOML stays static. A doctor-driven auto-enable
   mechanism is explicitly deferred to a future milestone, and (d) a pointer to
   its fixture in the T0 contrived repo.
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
- No built-in profile enables any check command by default (`pipeline.checks`
  is `[]` in every built-in TOML — there is no auto-enable path in v0.5.0;
  doctor-driven auto-enable is explicitly deferred). `revrem checks suggest`
  may recommend commands but never writes them into the profile. Verified by a
  test that loads each built-in profile and asserts `pipeline.checks == []`.

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

   > **What fake-harness tests prove — and what they don't.** The fake harness
   > replaces the model with scripted responses that *you write*. This means
   > these tests prove that the *configuration machinery* is wired correctly:
   > that when you run `revrem --profile security`, RevRem sends the security
   > profile's prompt to the model, interprets the response using the security
   > triage rules, and produces findings with the right severity policy. They
   > do NOT prove that a real model will flag real security bugs in real code —
   > that requires a human review or a live smoke run. The distinction matters:
   > if these tests pass but the live smoke fails, the problem is the *prompt
   > content* (T6), not the configuration machinery (T5). Keep the two concerns
   > separate when debugging.
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

## Release & Exit Criteria

v0.5.0 has two release tiers. Choose one before starting T13.

### Tier 1 — Minimum v0.5.0 Core (Pillars A + B, T0–T4 + T13)

Releasable when **Pillars A and B** meet their acceptance criteria. This closes
PLAN-003 M8, produces the "screenshot-worthy showcase" goal, and is the
recommended target when capacity is limited. Expert profiles (T5–T7) and DevEx
expansion (T8–T11) land as follow-on v0.5.x PRs; T12 is deferred to v0.6.0.
Record deferred pillars explicitly in CHANGELOG.

Gates:
- `./scripts/dev-check`, `pre-commit run --all-files`, `meminit check --format
  json`, and `git diff --check` pass; `lint-imports` is green.
- `revrem report` renders every T0 fixture deterministically and validates
  inputs against `summary-v1`/`events-v1` schemas; no model/network access.
- Headless output is ANSI-free on stderr with `--no-tty` and with `CI=true`
  in the environment; `test_headless_output.py` passes both assertions.
- The Action correctly discovers run directory from `--summary-format json`
  `artifact_dir` field; artifact-dir discovery test passes.
- Action continues to report/upload/comment on non-zero revrem exit; exit-code
  sequencing test passes.
- CI uploads default to redacted HTML report; raw upload requires
  `raw-artifacts: true`; redacted-upload test passes.
- The Action posts a single idempotent PR comment within the 5-minute metric
  on a ~1k-LOC PR and respects budget ceilings.
- At least one live dogfood run of `revrem --profile dogfood` (CLI) on a real
  branch, with `revrem report` rendering the result, is recorded before tagging.

### Tier 2 — Full v0.5.0 (Pillars A–D, all tasks except T12)

Releasable when Tier 1 gates pass **and**:
- ≥ 4 expert profiles flag their seeded issues with ≤ 20% pairwise overlap on
  the contrived repo, hermetically (fake harness, no network).
- Built-in profile precedence integration test passes all four shadowing cases.
- No built-in profile enables an ecosystem check by default; stack-detection
  test passes (`pipeline.checks = []` in every built-in TOML, confirmed by
  `test_builtin_profiles.py`).
- Examples validate in CI; completions emit for all three shells; the demo
  asset regenerates from a fixture; the failure-diagnostics guide has no code
  drift.
- Pillar E (TUI runs) either meets its acceptance criteria *or* is explicitly
  deferred to v0.6.0 in the CHANGELOG — it does not block the Tier 2 release.

## Mapping To The Path-To-1.0

This plan advances PLAN-003 as follows. After a **Tier 1** v0.5.0 release,
remaining roadmap work includes Pillars C + D (expert profiles, DevEx — as
v0.5.x follow-ons), the final M5 TUI slice (if deferred), and **M9** (archive,
dataset export, daemon). After a **Tier 2** v0.5.0 release, only the M5 TUI
slice (if deferred) and M9 remain — the natural v0.6.0/0.7.0 focus, leading to
the 1.0 "boring infrastructure" freeze.

| PLAN-003 milestone | Status after v0.5.0 |
|---|---|
| M0–M4, M6 | Done (v0.4.0) |
| M5 (TUI runs, hooks, headless) | Hooks/headless done; TUI real runs done **or** deferred (Pillar E) |
| M7 (expert profiles + DevEx) | **Done if Tier 2** (Pillars C + D); *partial* if Tier 1 only (Pillars C + D deferred to v0.5.x) |
| M8 (CI surface + HTML report) | **Done** (Pillars A, B) |
| M9 (archive, daemon, dataset) | Next (v0.6.0+) |

## Pre-Sprint Decisions

These questions were identified during planning review and are resolved here
so implementers do not encounter them as surprises mid-sprint. Record any
future changes to these decisions as ADRs (`REVREM-ADR-0NN`).

**D-1 (T4): `action.yml` lives at the repo root for v0.5.0.**

GitHub's composite action lookup finds `action.yml` at the repository root
when a user writes `uses: owner/revrem@v0.5.0`. This is the path of least
resistance: no separate marketplace repo to maintain, no cross-repo
synchronisation. If a standalone marketplace listing is wanted in the future,
move the file at that time — no behaviour change required. Ref: PLAN-003 OQ5.

**D-2 (T5/T6): Reuse the existing profile TOML schema for all built-in
profiles. Add new manifest fields only if a specific profile genuinely
requires them.**

The current profile schema already covers all the structure expert profiles
need. The relevant TOML tables and keys are: `[pipeline]` (with `checks = []`
as a list of shell commands — there is no standalone `[checks]` table);
`[triage]` (top-level); and `triage.routing` (a sub-table nested *inside*
`[triage]`, not a top-level `[routing]` table).

**Budget fields are forbidden in built-in profiles.** Built-in TOMLs must not
set `max_iterations`, `max_usd`, or `max_wall_seconds`. Budget is a user/project
concern; a built-in that silently raises a user's budget cap would violate
Contract #5 (additive-safe changes must not surprise existing users). Add a test
to `test_expert_profiles.py` asserting that no built-in TOML contains any of
these keys. Built-ins should only set `description`, `[triage]` routing/severity
rules, and `pipeline.checks = []`.

Do not create a new `expert-profile-v1` schema preemptively — schemas add maintenance overhead
(history baselines, migration notes, version bumps). If a specific future
profile needs a field the schema does not have (e.g. a `self_skip_when`
accessibility check), add it additively at that point following Contract #7
and Contract #8, and create a schema history baseline then.

**Profile metadata for user-facing presentation (name, description, date,
narrative note):** The existing `description` field (a free-text string in the
profile TOML's top-level `description =` key) is the narrative for v0.5.0 —
each built-in TOML's `description` should be a one-to-two sentence statement
of the profile's purpose and intended audience. This is sufficient for
`revrem config list` and `--dry-run` output. **Do not add `date_created` or a
separate narrative-note field in v0.5.0** — date provenance is available from
`git log -- src/code_review_loop/expert_profiles/<name>.toml` and a dedicated
presentation field would require schema versioning. If a future UX surface
(e.g. a profile browser in the TUI) genuinely needs structured metadata,
add a `[meta]` table additively at that point per Contract #7.

> **Example:** `security.toml` does not need a `self_skip_when` field for
> v0.5.0 — it is a universally applicable profile. A future `accessibility`
> profile might need it. Add the field only when the profile needs it, not
> speculatively.

**D-3 (T2): Provide the `--format json` index from `revrem report`.**

A machine-readable report index is cheap to produce (a small dict alongside
the HTML renderer) and unlocks a useful CI integration pattern: the Action
can read artifact paths from JSON without parsing HTML, and future tooling
can consume it without understanding the HTML layout. HTML remains the primary
human-readable output; the JSON index is the machine-readable companion.
Both are additive-safe per Contract #7.

The JSON index is a *summary* (schema version, run ID, final status, finding
counts by severity, suppression count, `cost_usd`, `top_findings` of at most
5 redacted finding summaries with severity/file/line/one-sentence title, and
artifact paths) — it is NOT a duplicate of `summary.json`. It is the minimum
payload needed for `post_pr_comment.py` to build a complete PR comment body
without reading raw events or summary files. Think of it as: "what do I need
to know to comment on this run and link to the report?"

**D-4 (T12 / Pillar E): Treat TUI real runs as stretch; cut at the T0/T1
review gate.**

TUI real runs (T12) do not gate the showcase goal (Pillars A + B are the
milestone delivery). T12 carries the highest implementation risk in the plan
because it touches the Textual UI boundary and requires Pilot test coverage.
At the T0/T1 review gate, assess remaining capacity:
- If T1 and T2 are on track and a stronger model or human pairing is
  available, proceed with T12.
- Otherwise, defer explicitly to v0.6.0 and record the deferral in the
  CHANGELOG.

Do not start T12 if T4 is not yet complete and accepted. T4 is the primary
milestone delivery for v0.5.0.

**D-5 (T3): Headless suppression uses `CI=true` auto-detection plus `--no-tty`.**

See T3 step 1 for the full design. In short: `CI=true` (set automatically by
GitHub Actions, CircleCI, Travis, Jenkins, and most other providers) triggers
auto-suppression without any flag; `--no-tty` provides an explicit override
for non-standard environments and local scripting. Both write to the same
gate in `progress.py`. `--progress-style compact` is the recommended
accompanying setting for CI logs.
