---
document_id: REVREM-PLAN-003
type: PLAN
title: Post-Launch Development Roadmap
status: Approved
version: '0.8'
last_updated: '2026-06-01'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Post-launch roadmap that takes RevRem from a usable MVP to a hardened, hands-off coding-assistant utility, sequencing trust, autonomy, distillation, and showcase capabilities behind explicit quality gates.
keywords:
- revrem
- roadmap
- hardening
- devex
- distribution
- autonomy
- distillation
- showcase
related_ids:
- REVREM-PRD-001
- REVREM-PLAN-002
- REVREM-DEVEX-001
- REVREM-TEST-001
- REVREM-TASK-001
- REVREM-TASK-002
- REVREM-TASK-006
---

# PLAN: Post-Launch Development Roadmap

## Context

RevRem has completed its first public GitHub launch as a watched local
review → remediate → verify loop. The launch validated the *shape* of the
product: a bounded, artifact-producing, operator-trusted utility that turns a
code reviewer model and a verification suite into a pre-merge confidence
engine.

The next stretch of work has to do something harder than "launch": it has to
turn a credible MVP into a tool that an external developer reaches for
*reflexively* — installable in seconds, trustworthy in failure, predictable
under automation, and visibly distinct from "a wrapper around an LLM".

The user-visible question is no longer "does the loop run?" It is:

1. Can a skeptical developer install RevRem in under a minute and get a useful
   first run on their own repository?
2. When something goes wrong, does RevRem explain itself well enough that the
   operator never has to read its source?
3. Can the same tool plausibly run in three modes — interactive CLI, watched
   TUI, and *hands-off* CI/hook automation — without forking its execution
   model?
4. Does each new run leave behind structured evidence that compounds — for
   the operator (history, suppressions), for the team (dashboards), and for
   future model post-training?
5. Does the product *feel* like a showcase of what a small, principled,
   local-first agentic tool can be — not a demo, not a SaaS funnel?

This plan answers those questions as a sequenced, parallelizable programme of
work, with explicit non-goals, quality bars, and a 1.0 stability target. It is
intentionally ambitious, but every milestone must still be independently
shippable by a small maintainer team. Ambition without slice discipline is a
failure mode for this project.

## North Star

> **RevRem is the local, watched, evidence-producing review-and-remediation
> loop that a developer trusts to run hands-off on their branch — and trusts
> enough to publish what it found.**

Three properties are non-negotiable:

- **Local-first.** No hosted backend, no telemetry, no required cloud account
  beyond the user's chosen model provider. Artifacts live on disk.
- **Bounded by default.** Every autonomous mode has explicit iteration, time,
  and cost ceilings; "unbounded" is always an opt-in flag, never a default.
- **Honest in failure.** A failed run is a *first-class output*, not an
  exception path. Diagnostics, partial artifacts, and remediation hints are
  contractual — not best-effort.

Everything in this roadmap either reinforces those properties or extends them
into new surfaces (CI, archive, expert profiles, additional harnesses).

## Personas & Autonomy Ladder

Roadmap decisions get sharper when they map to a specific user at a specific
autonomy level. RevRem's value proposition climbs a ladder:

| Level | Persona | How RevRem is used | Roadmap dependency |
|---|---|---|---|
| **L0 — Interactive** | Solo dev, exploratory | Single `revrem` invocations, eyes-on-terminal | Shipped today |
| **L1 — Profile-driven** | OSS maintainer, repeat user | `revrem --profile pr-ready`, watched | M2–M3, M7 |
| **L2 — Pre-merge gate** | IC who pre-flights every PR | `revrem` as a Git pre-push or pre-commit hook | M2, M4, M5 |
| **L3 — Hands-off CI** | Small-team platform owner | RevRem GitHub Action posts findings/diff comment | M5, M6, M8 |
| **L4 — Background distiller** | Power user / research | Daemon mode reviews branches as they're pushed; archives feed dashboards or fine-tunes | M5, M6, M9 |

Each milestone in this plan is annotated with the highest autonomy level it
unlocks. The ladder is the roadmap's primary success rubric: by the end of the
plan, RevRem must be credibly usable at L4 by an internal user, and at L3 by
an external one.

## Success Metrics

Quantitative gates the roadmap must move. Numbers are post-launch baselines —
all measurable locally; none depend on telemetry.

| Metric | Baseline (today) | Target by 1.0 | Owned by milestone |
|---|---:|---:|---|
| Time from `pipx install` to first useful run | n/a (no PyPI) | < 90 s on a sample repo | M1 |
| `revrem doctor` catches misconfigurations before launch | partial | ≥ 95% of known failure modes | M2 |
| P50 wall-clock for a "clear" run on the reference repo | ~3 min | ≤ 2 min | M2, M4 |
| Triage precision on a labelled review fixture set | n/a | ≥ 0.85 (no false suppressions of real bugs) | M3 |
| Cost-cap respected (no run exceeds declared `$`/token budget) | not enforced | 100% of runs | M4 |
| Replayable runs from event fixtures | 0% | 100% of integration tests | M4 |
| Hands-off CI mode posts a useful comment within 5 min on a 1k-LOC PR | n/a | yes, on reference repo | M5, M8 |
| Bundled expert profiles produce distinct, non-redundant findings on a contrived bug suite | n/a | ≥ 4 profiles, ≤ 20% finding overlap | M7 |
| Mean time to actionable diagnosis on a failing run | "varies" | < 60 s reading `summary.json` + `diagnostics.json` | M2 |
| Public repo "good first issue" → first external PR merged | 0 | ≥ 3 by 1.0 | M7 |

These metrics, not feature counts, define when the roadmap is "done".

## Critical Assessment Of The Programme

The roadmap is strong because it identifies the right product wedge: trusted
local automation with inspectable evidence. The highest-risk parts of the plan
are not model quality or UI polish; they are scope coupling and premature
surface-area expansion.

Final review corrections:

- **Do not let the TUI become a second execution engine.** `run_loop()` or its
  extracted successor remains the only execution owner. The TUI, reports, CI
  comments, and replay consume events.
- **Do not ship archive/daemon work before suppression and budget controls.**
  A background reviewer without suppressions becomes noisy; one without budgets
  becomes unsafe.
- **Do not add real secondary harnesses before a fake harness contract.** The
  fake harness is not a test convenience; it is the executable specification
  for every future backend.
- **Do not call PyPI "done" at first upload.** Distribution is done only when a
  fresh user can install with `pipx`, run a documented profile, and diagnose a
  failed setup without source access.
- **Do not optimize for maximal autonomy before trust.** Hands-off operation
  must be earned by preflights, schema stability, cost ceilings, cancellation,
  and suppressions.

The governing principle for roadmap triage is therefore:

> If a feature increases autonomy, it must first increase or preserve
> diagnosability, boundedness, and artifact quality.

## Showcase Definition

"Showcase" has a precise meaning in this plan. RevRem should be impressive
because it is operationally composed, not because it has the largest feature
list.

The 1.0 showcase demo is:

1. A maintainer installs RevRem with one public command.
2. They run a bundled `pr-ready` or `security` profile on a sample repository.
3. RevRem preflights the repo, explains the plan, and enforces an explicit time
   and cost budget.
4. It reviews, triages, remediates, verifies, and either exits clear or leaves
   a compact, self-contained failure bundle.
5. The same run can be replayed in compact terminal output, Rich/TUI output,
   static HTML report, and CI comment without re-running a model.
6. A repeated run suppresses intentionally-dismissed findings and highlights
   only new or changed risk.
7. The run artifacts are schema-versioned and privacy-scrubbed before any
   export.

Anything that does not move this demo forward is lower priority, even if it is
technically interesting.

## Strategic Themes

Five themes thread through every milestone. Each PR should be classifiable
under one or two of them; PRs that fit none should be questioned.

1. **Trust** — distribution, provenance, diagnostics, reproducibility,
   versioned artifacts, supply-chain hygiene.
2. **Autonomy** — moving up the L0 → L4 ladder safely: budgets, suppressions,
   resumability, hooks, CI surface, daemon mode.
3. **Distillation** — every run produces structured, privacy-aware,
   schema-versioned evidence that compounds: history, archive, suppressions,
   dashboards, datasets.
4. **Versatility** — expert profiles, multi-language examples, harness
   pluralism, plugin entry points; one engine, many lenses.
5. **Craft** — the showcase axis: terminal UX, error copy, README, demo asset
   quality, documentation tone, error messages a stranger would screenshot.

## Dependency Gates

These gates prevent late milestones from smuggling in unstable contracts.

| Gate | Required before | Evidence |
|---|---|---|
| **G1: Public distribution smoke** | Any README install claim using PyPI/pipx | Fresh virtualenv or `pipx` CI job proves install and `revrem --version` |
| **G2: Diagnostic schema v1** | Triage schema, events, report, CI Action, archive | JSON schema plus fixture validation in CI |
| **G3: Suppression semantics** | Hooks, headless CI, daemon/watch | Tests prove suppressed findings do not trigger remediation but remain visible |
| **G4: Budget enforcement** | Hooks, CI Action, daemon/watch, secondary harnesses | Fixture proves the next model call is not started after ceiling breach |
| **G5: Event replay** | TUI run execution, static report, CI comments | `revrem replay` renders fixture runs without model/network access |
| **G6: Fake harness contract** | Claude/Gemini/opencode adapters | Fake harness covers review, triage, remediation, timeout, cancellation, cost gaps |
| **G7: Redaction harness** | Bug bundles, archive export, CI comments | Poisoned fixture with synthetic secrets is scrubbed by default |

If a PR depends on a gate that has not landed, it should be split or deferred.

## Recommendation

Sequence the roadmap in three concurrent tracks rather than one queue. The
single-queue framing in the prior draft is an artifact of solo capacity, not
a dependency truth: distribution, hardening, and triage have largely
independent risks and can land in parallel once M0 lands.

**Track A — Trust & Distribution (serial, fastest critical path).**
M0 (public-trust baseline) → M1 (PyPI, pipx, provenance) → M2 (preflight,
diagnostics, artifact schema). External adoption is gated on this track.

**Track B — Workflow & Autonomy (parallelizable after M0).**
M3 (triage productization, suppressions) → M4 (event stream + cost governance
+ replay) → M5 (TUI runs + hooks + headless CI mode). This track climbs the
autonomy ladder.

**Track C — Distillation & Showcase (parallelizable after M3 lands).**
M6 (harness contract + secondary adapter) → M7 (expert profiles + DevEx
expansion) → M8 (CI/Action surface + report rendering) → M9 (archive,
dataset, daemon, dashboards).

Headline priorities, in plain language:

1. **Distribution and release trust.** Every external user hits this first;
   it gates everything else.
2. **Operational hardening, diagnostics, and a published artifact schema.**
   RevRem's brand is honest failure. The schema is what lets every
   downstream — TUI, CI, dashboards, dataset export — exist without
   re-implementing parsing.
3. **Triage as a first-class workflow with suppressions.** Suppressions are
   the missing primitive that makes hands-off operation tolerable: a finding
   the operator has dismissed should not re-surface every run.
4. **Event stream + cost governance + replay.** One execution model feeding
   CLI, Rich, history, TUI, CI, and replay tests. Cost ceilings are a
   first-class concept here, not a M9 afterthought.
5. **Hands-off surfaces (hooks, GitHub Action, headless mode).** This is
   what turns "interesting tool" into "ambient infrastructure" for the user.
6. **Expert profiles + secondary harness.** Showcase versatility: same
   engine, different lens; same loop, second model.
7. **Distillation archive + static report + dataset export.** Compounding
   value, suitable for fine-tuning or org dashboards, never auto-uploaded.

The most under-weighted item in the prior draft was **suppressions**: without
them the L2/L3/L4 levels of the autonomy ladder produce noise, and noise
kills hands-off automation faster than any model quality issue.

## Decision Matrix

Expanded with effort and a "showcase" axis (does shipping this materially
change how the project is perceived?).

| Candidate | User value | Risk | Effort | Showcase | Dependency | Priority |
|---|---:|---:|---:|---:|---|---:|
| PyPI / pipx / provenance | High | Med | Med | High | Workflow + metadata | P0 |
| Failure diagnostics + artifact schema | High | Low | Med | Med | Existing CLI | P0 |
| `revrem doctor` / preflight | High | Low | Low | Med | Diagnostics | P0 |
| Triage productization + suppressions | High | Med | Med | High | Artifact schema | P1 |
| Event stream + replay harness | High | Med | High | Med | Schema | P1 |
| Cost governance (budgets, ceilings, accounting) | High | Low | Low | Med | Event stream | P1 |
| Pre-push / pre-commit hook integration | High | Low | Low | Med | Cost caps + diagnostics | P1 |
| Advisory check discovery from repo hooks/config | High | Low | Low | Med | Diagnostics + profiles | P1 |
| Headless / non-TTY mode hardening | High | Low | Low | Low | Event stream | P1 |
| TUI starts real runs | Med | High | High | High | Event stream + cancellation | P2 |
| Expert profiles (security, perf, a11y, refactor) | High | Low | Med | High | Profile schema | P2 |
| Static HTML run report (`revrem report`) | Med | Low | Low | High | Schema | P2 |
| GitHub Action / CI surface | High | Med | Med | High | Headless + report | P2 |
| Secondary harness adapter (Claude/Gemini CLI) | Med | High | Med | High | Harness contract | P2 |
| Indexed remediation archive + dataset export | Med | Med | Med | High | Schema + privacy scrub | P3 |
| Background daemon / branch-watcher | Med | High | Med | Med | Hooks + budgets | P3 |
| Plugin entry points (checks/harnesses) | Med | Med | Med | Low | Stable contracts | P3 |
| Public DevEx polish (asciicast, examples, FGI) | High | Low | Low | High | Schema/profiles | P1 |
| Hosted Web UI | Low | High | High | Low | Strategy change | Defer |
| Full provider marketplace | Low | High | High | Low | Multiple harnesses proven | Defer |

## Anti-Roadmap (What We Will Not Build)

Calling out non-goals explicitly is part of the showcase: a tool that knows
what it is not.

- **No hosted service or signup.** RevRem stays installable, local, and
  inspectable. Anything cloud-shaped is a separate project.
- **No silent telemetry.** Run history is local-only; archive export is
  opt-in and never auto-transmitted.
- **No "fix anything" mode.** Remediation stays bounded by iteration count,
  wall-clock, *and* cost. There is no `--unlimited` flag without a
  paired `--i-understand-the-cost`.
- **No vendor abstraction before two harnesses are proven.** A "model
  marketplace" written before the second adapter exists is speculative
  surface area.
- **No IDE plugin in this plan window.** CLI + TUI + CI is the surface; an
  IDE integration would be its own product.
- **No ML/agent training inside RevRem.** The archive is shaped for export;
  consumers train.

## Capability Maturity Checkpoints

The plan deliberately separates "available", "default", and "stable". A
feature should not skip levels because it works once on the maintainer's
machine.

| Level | Meaning | Required evidence |
|---|---|---|
| **Experimental** | Hidden behind an explicit flag or profile field; allowed to change | Unit tests plus one documented manual smoke |
| **Preview** | Documented for adventurous users; schema may be additive-only but not frozen | Fixture tests, failure docs, and at least one non-maintainer-style example |
| **Default-on for local use** | Safe for normal watched CLI usage | Preflight coverage, diagnostics, bounded cost/time, artifact schema validation |
| **Default-on for hands-off use** | Safe in hooks/CI without a human watching stdout | Suppressions, budgets, cancellation, redaction, stable exit codes |
| **Stable contract** | SemVer-protected public surface | Versioned schema, migration notes, compatibility tests against prior fixtures |

Every milestone below must state which maturity level it reaches. For example,
the first Claude adapter can be **Experimental** in M6; it is not allowed to
become a default backend until it passes the same hands-off gates as Codex.

## Milestones

Each milestone declares: goal, autonomy level reached, scope, acceptance
criteria, and the *quality bar* a reviewer should hold the PR to.

### Milestone 0 — Public Trust Baseline

**Autonomy:** L0. **Theme:** Trust, Craft.

**Goal.** Finish the post-launch public-project baseline so the repository
does not look half-published or internally oriented. This is the pre-condition
for every track that follows.

**Scope.**
- Default branch, branch protection, security policy, CI badges, and release
  page reflect the public `main` branch.
- Issue templates and labels for `bug`, `enhancement`, `docs`, `debt`,
  `good first issue`, `help wanted`, `triage`, `harness`, `tui`.
- Confirm Dependabot version updates target `main`; close stale launch PRs
  rather than merge them.
- Add a fresh `main` push after default-branch correction so Scorecard
  evaluates a valid event payload.
- Keep `README.md` external-facing; relocate internal release checklists
  into governed docs (`docs/05-planning` or `docs/70-devex`).
- Add a one-paragraph "What RevRem is / is not" panel above the install
  fold.

**Acceptance criteria.**
- GitHub shows `main` as the default branch; only expected long-lived
  remote branches remain.
- CI is green on `main`; the required CI job executes the same substantive
  gates as local `./scripts/dev-check` and the configured pre-commit hooks.
- Branch protection requires the Python CI checks before merge.
- Security policy and dependency alerts are enabled.
- README badges resolve to real, green, public targets.
- `./scripts/dev-check` passes locally.

**Quality bar.** A reviewer landing on the repo with no prior context can
answer "what is this and how do I install it" inside 60 seconds.

### Milestone 1 — Install And Release Distribution

**Autonomy:** L0 → L1. **Theme:** Trust, Craft.

**Goal.** Make `revrem` installable and updatable through a standard external
path while preserving the repo-local dev/stable workflow used by the
maintainer.

**Scope.**
- Settle package identity before publication:
  - publish as `revrem` on PyPI (primary name); `code-review-loop` remains
    as the distribution and console-script alias for backward compatibility.
- Promote contributor release guidance into a governed release plan
  (`REVREM-PLAN-NNN`), separate from `README.md`.
- Harden package metadata: description, URLs, classifiers, keywords,
  optional extras (`progress`, `tui`, `archive`, `ci`), license expression,
  README rendering, long-description validation.
- CI workflow for sdist + wheel build, `twine check`, and a fresh-venv
  install smoke test.
- TestPyPI publish on a tag pattern (e.g. `v*.*.*-rc*`); PyPI publish on a
  signed release tag.
- Sigstore / `attest-build-provenance` artifacts; SHA-256 checksums attached
  to GitHub Releases.
- Document install modes:
  - `pipx install revrem` for normal users (recommended);
  - `pip install revrem` for managed envs;
  - `uv tool install revrem` for `uv` users;
  - source checkout + `./scripts/install-dev` for contributors;
  - `./scripts/promote-stable` for the maintainer's local multi-repo flow.
- Investigate and document (not necessarily ship): single-file `shiv`/
  `pex`/PyInstaller artifact, a Homebrew tap formula stub, a minimal
  container image (`ghcr.io/...`).

**Acceptance criteria.**
- `python -m build`, `twine check`, smoke install pass in CI.
- TestPyPI install works in a fresh venv on Linux and macOS runners.
- PyPI install or `pipx install` exposes `revrem --version` < 90 s on a
  reference machine.
- Release artifacts have provenance and checksum coverage.
- README install section is updated only after the package is published.
- Rollback is documented: a bad PyPI release can be yanked, the GitHub release
  can be marked superseded, and users can pin the previous known-good version.
- The release workflow refuses to publish if the working version in
  `pyproject.toml`, `src/code_review_loop/__init__.py`, and the release tag do
  not agree.

**Quality bar.** A user who has never seen this repo can copy one line
from the README and have a working `revrem` on `PATH` in under 90 seconds.

**Why this comes before GUI.** External users cannot benefit from a richer
GUI if installation still requires cloning the repository and trusting
local scripts. Distribution is the first conversion bottleneck.

### Milestone 2 — Runtime Hardening, Diagnostics, And Schema

**Autonomy:** L1 → L2. **Theme:** Trust, Distillation.

**Goal.** Make failure modes fast, local, and self-diagnosing, and ratify
the artifact schema that every downstream surface (TUI, CI, archive, report)
will depend on.

**Scope.**
- Expand review-base preflights: invalid base, no merge base, dirty worktree
  with commit mode, missing Codex executable, Codex auth/config not usable,
  check commands not found, network-required model offline, low disk space
  in artifact dir.
- Ship `revrem doctor` (alias `revrem preflight`) with `--format json`
  stable enough for agents and CI; exit code distinguishes "blocking",
  "warn", "ok".
- Enrich timeout artifacts with: command, cwd, elapsed, process-group
  cleanup result, partial stdout/stderr (size-bounded), likely-cause hints.
- Publish a versioned **artifact schema**
  (`docs/52-api/revrem-artifact-schema-v1.json`) covering `summary.json`,
  `diagnostics.json`, `events.jsonl`, `triage.json`, and `archive/*.json`.
  Add a `schema_version` field to each.
- Add `revrem bundle-bug-report` to produce a redacted, secret-free
  diagnostics tarball for issue submission.
- Add stable failure fingerprints so repeated setup failures, timeout classes,
  and review parsing failures can be searched across local history without
  exposing raw review text.
- Make run history append-safe under interruption and read-safe under
  truncation; add a fsync-once-per-run policy with a fallback for ENOSPC.
- Add a corpus of "failure scenarios" fixtures to `REVREM-TEST-001`.

**Acceptance criteria.**
- Common invalid setup states fail before launching Codex.
- Every failed phase writes an artifact and a non-empty `diagnostics.json`.
- Timeout tests cover direct children and pipe-holding descendants.
- `revrem preflight --format json` validates against the published schema.
- Schema doc is referenced from the README and CONTRIBUTING.
- ≥ 95% of known misconfigurations in the test corpus are caught pre-launch.
- `bundle-bug-report` redacts synthetic secrets and excludes raw local
  transcripts unless explicitly requested.

**Quality bar.** A failed run can be diagnosed without reading source code.
A tester can construct a contrived breakage and predict the diagnostic
output from the schema.

### Milestone 3 — Triage Productization And Suppressions

**Autonomy:** L1 → L2. **Theme:** Autonomy, Distillation.

**Goal.** Promote triage from optional intermediate pass to the canonical
way to separate true findings, false positives, implementation order, and
verification requirements before remediation — and introduce *suppressions*
so dismissed findings stop returning every run.

**Scope.**
- Define a triage artifact contract:
  - confirmed actionable findings;
  - rejected findings with a one-line rationale;
  - "needs more info" findings (do not block, do not remediate);
  - severity (`info`/`low`/`medium`/`high`/`critical`);
  - files/modules affected;
  - suggested implementation order;
  - required verification commands.
- Add `--triage`, profile defaults, and clear help-text framing of
  "when triage helps".
- Feed triage into remediation prompts without losing original review
  context (referencing, not replacing, the review excerpt).
- Define a **suppression file** at `.revrem/suppressions.toml` keyed by a
  stable finding fingerprint (path + normalized rule id + content hash).
  A suppressed finding produces a one-line `suppressed` event but does not
  trigger remediation. Suppressions can carry an `expires` field so they
  decay rather than rot.
- Require suppressions to record provenance: who/what created the suppression,
  original finding summary, creation time, optional expiry, and whether it is
  repo-committed or user-local.
- Add `revrem suppress add|list|remove|expire` for operator workflow.
- Add tests for triage failure, timeout, false-positive handling,
  prompt-size truncation, suppression match/no-match, expiry.
- Document the workflow: review → triage → suppress-or-remediate → verify.

**Acceptance criteria.**
- Triage can be enabled from CLI and profile config.
- Triage artifacts are linked from `summary.json` and conform to the schema.
- Remediation receives triage guidance plus original review excerpts.
- Invalid triage output fails safe rather than suppressing review findings.
- Suppressions are honoured by both interactive and headless modes.
- Triage precision on the labelled fixture set ≥ 0.85.
- No suppression can hide a `critical` finding unless the operator passes an
  explicit override flag that is recorded in the suppression entry.

**Quality bar.** An operator running RevRem twice in a row on the same
unchanged branch sees zero re-asked questions about findings they have
already dismissed.

**Why this beats immediate non-OpenAI support.** Triage and suppressions
improve quality and tolerability for *every* backend. Adding harnesses
without these primitives multiplies noise instead of value.

### Milestone 4 — Event Stream, Cost Governance, And Replay

**Autonomy:** L2. **Theme:** Distillation, Autonomy, Trust.

**Goal.** One loop event model that feeds compact progress, Rich progress,
history, diagnostics, the TUI, the CI surface, and replay tests — with cost
governance and reproducibility as first-class concerns.

**Scope.**
- Define typed events: `phase_start`, `phase_output`, `phase_result`,
  `status_classification`, `check_result`, `artifact_write`, `warning`,
  `failure`, `summary`, `cost_charge`, `cost_ceiling_hit`, `cancellation`,
  `suppressed`. Each event has `schema_version`, `run_id`, `seq`, `ts`.
- Replace ad hoc progress calls with an event sink interface.
  Compact/Rich renderers become consumers, not producers.
- Persist `events.jsonl` per run; downstream surfaces read this file
  rather than re-parsing transcripts.
- Define event compatibility rules: new event fields are additive within a
  major version; removed or renamed fields require a schema-major bump and a
  migration note.
- **Cost governance.** Each run takes optional `--max-tokens`, `--max-usd`,
  `--max-wall-seconds`. Ceilings are checked between phases and on every
  `cost_charge` event; hitting one triggers `cost_ceiling_hit` and a
  graceful, artifact-preserving stop. `summary.json` always reports
  observed token/cost totals (zero when the harness can't report them).
- **Replay.** `revrem replay <run-dir>` re-renders any past run from
  `events.jsonl` into the current renderer (compact/Rich/TUI), without
  re-invoking the model. Replay is the integration-test substrate for the
  TUI, the CI report, and the static HTML report.
- Cancellation semantics: a single Ctrl-C drains in-flight phases, writes
  artifacts, emits `cancellation`, exits non-zero with a stable code.
- Determinism affordances: pin model + harness version into `summary.json`;
  surface a `--seed` flag where the harness supports it; record the exact
  command line.
- Add golden event fixtures for the reference scenarios: clear review,
  actionable finding fixed, rejected false positive, timeout, check failure,
  cancellation, and budget ceiling.
- Update `REVREM-PLAN-002` when this foundation is ready to unblock real
  TUI-launched runs.

**Acceptance criteria.**
- CLI output remains compatible with current tests.
- JSON event fixtures cover clear, findings, unknown, timeout, check
  failure, cost-ceiling hit, suppression, and cancellation.
- TUI renders a replayed run from event fixtures before it starts real
  runs (gates M5).
- No second implementation of review/remediation execution exists.
- Cost ceilings are honoured 100% of the time in tests; a run that
  exceeds its ceiling fails *before* spending the next dollar.
- `revrem replay` reproduces a finished run's terminal output byte-for-byte
  for the compact renderer (Rich/TUI may differ on theme).
- Event fixture tests run without Codex, network, or GitHub access.

**Quality bar.** Every downstream surface in this roadmap can be built
*without* re-reading raw Codex transcripts.

### Milestone 5 — TUI Runs, Hooks, And Headless Mode

**Autonomy:** L2 → L3. **Theme:** Autonomy, Craft.

**Goal.** Let the TUI start, monitor, cancel, and summarize real runs;
make RevRem behave correctly when nobody is watching.

**Scope (TUI runs).**
- Start runs from selected profiles.
- Show current phase, model, base branch, checks, elapsed, cost so far,
  artifact paths.
- Cancellation with terminal/process cleanup verified by Pilot tests.
- Distinct visual states for clear / findings / unknown / failure /
  cost-ceiling-hit.
- Link to latest review, remediation, checks, summary, archive entries.
- Keep "copy command" and "run in terminal" affordances.

**Scope (hooks).**
- Ship `scripts/hooks/pre-push` and `scripts/hooks/pre-commit` examples
  that invoke `revrem` with sensible bounded defaults.
- Document `revrem install-hooks` (opt-in command) for the target repo,
  including uninstall and idempotency.
- Hooks must respect cost ceilings and produce a one-line pass/fail
  summary; full output stays in `.revrem/runs/...`.
- Treat `git commit` hook failures as first-class verification failures, not
  unexpected crashes. The default policy is to feed the hook output into the
  next bounded remediation pass when iterations remain, preserve staged
  changes and artifacts, and stop gracefully with `stopped_reason:
  commit_hook_failed` when the loop is exhausted. `--no-verify` is an explicit
  operator policy only; it is recorded in run artifacts and never used as a
  silent optimization.

**Scope (advisory check discovery).**
- Add a read-only `revrem checks suggest` / `revrem doctor checks` surface
  that inspects the target repository and proposes `--check` commands with a
  confidence level, rationale, and caveats.
- Discover likely verification sources without executing them: configured
  `core.hooksPath`, `.git/hooks/pre-commit`, `.git/hooks/pre-push`,
  `.pre-commit-config.yaml`, `.githooks/`, package scripts, `tox.ini`,
  `noxfile.py`, `pyproject.toml`, `Cargo.toml`, `go.mod`, and similar
  language-native markers.
- Model suggestions as structured data, e.g. `command`, `source`, `phase`
  (`pre-commit`, `pre-push`, `test`, `lint`, `typecheck`), `confidence`,
  `requires_network`, `estimated_cost`, and `notes`. This lets agents and
  profile writers decide what to include without scraping prose.
- Keep the first version advisory only. It must not auto-edit profiles,
  install hooks, or assume hook parity. A future `--write-profile` can be
  added only after users can preview and diff the generated profile.
- Document the mental model clearly: pre-running discovered checks reduces
  redundant hook failures, but the actual `git commit` remains the
  authoritative integration point because hooks can depend on staged files,
  environment variables, local tool versions, and hook-managed re-staging.

**Scope (headless).**
- `--no-tty`/auto-detect: disable progress animation, emit stable
  line-oriented logs suitable for CI capture.
- Stable, documented exit codes (0 clear, 2 findings, 3 ceiling hit,
  4 setup failure, 5 cancelled, 1 unexpected error).
- Resumability: if a run was interrupted mid-phase and the worktree is
  unchanged, `revrem resume` continues from the last completed phase
  using `events.jsonl` + the existing artifact dir.

**Acceptance criteria.**
- A TUI-launched run produces the same artifacts and summary as the
  equivalent CLI run.
- Pilot tests cover launch, cancellation, cost-ceiling, and ≥ 3 failure
  states.
- Hook examples land green in CI for the reference repo.
- `git commit` hook failures produce a commit artifact, a structured summary
  reason, and either another remediation pass or a graceful bounded failure;
  they do not leave the operator with a Python traceback as the primary
  diagnostic.
- Check discovery suggests the reference repo's substantive local checks and
  rejects unsupported or unsafe guesses with explicit caveats.
- Headless mode produces output that is grep-able and free of ANSI
  escapes when stdout is not a TTY.
- `revrem resume` produces an identical final `summary.json` to a
  matched uninterrupted run on the same fixture.

**Quality bar.** A user can run `git push` and have RevRem block the push
on findings without ever opening a terminal RevRem started.

### Milestone 6 — Harness Contract And Non-OpenAI Backends

**Autonomy:** L2 → L3. **Theme:** Versatility, Trust.

**Goal.** Support additional review/remediation engines without the loop
depending on Codex-specific assumptions.

**Scope.**
- Define a backend/harness capability contract:
  - review command shape;
  - remediation command shape;
  - stdin/stdout behavior;
  - sandbox/write controls;
  - model configuration;
  - timeout/cancellation behavior;
  - structured output support;
  - cost reporting (token + USD where available);
  - unsupported feature reporting.
- Add a fake harness used by tests to prove the contract independent of
  Codex. The fake replays scripted phase outputs from event fixtures.
- Move Codex-specific status parsing behind the harness boundary.
- Add one real secondary adapter only after the fake harness and docs are
  stable. **Preferred first secondary:** Claude CLI (good non-interactive
  exec semantics, structured output support). Gemini CLI is the next
  candidate. OpenRouter / generic HTTP is explicitly *not* the first
  choice — it would require building agentic loop machinery inside
  RevRem.
- Profile schema gains `supported_harnesses` / `unsupported_harnesses`
  lists with clear validation messages.

**Acceptance criteria.**
- Profiles can declare supported and unsupported harnesses with clear
  validation.
- Fake harness test suite covers review, remediation, triage, timeout,
  cost-ceiling, cancellation, and unsupported-feature paths.
- A real secondary harness has documentation, examples, failure
  diagnostics, and matches the same `summary.json` shape as Codex.
- Existing Codex behavior is not regressed (golden fixtures unchanged).

**Quality bar.** A reviewer cannot tell from `summary.json` shape alone
which harness ran the loop.

### Milestone 7 — Expert Profiles And Public DevEx Expansion

**Autonomy:** L1 → L3. **Theme:** Versatility, Craft.

**Goal.** Make RevRem easier to evaluate, learn, and contribute to;
showcase versatility through deeply-tuned out-of-the-box personas.

**Scope (expert profiles).** Each is *not* a renamed default — each ships
a tuned system prompt, a tailored triage rubric, a recommended check
matrix, severity policy, and a small fixture set the profile is known
to flag correctly.

- **`security`** — vuln classes, secret leakage, unsafe deserialization,
  authn/authz drift, dependency CVE delta. Pairs with `pip-audit` /
  `npm audit` style checks.
- **`performance`** — algorithmic complexity, hot-path allocations,
  N+1 patterns, sync-in-async. Pairs with benchmark/profile checks where
  the repo has them.
- **`accessibility`** — semantic HTML, ARIA misuse, contrast, keyboard
  traps. Frontend repos only; profile must self-skip on detection.
- **`refactor`** — duplication, dead code, leaky abstractions, naming
  clarity. Lower default severity; never blocks on its own.
- **`migration`** — diff-aware safety: schema migrations, backwards
  compatibility, deprecation handling. Designed to pair with PR review
  rather than replace it.
- **`docs`** — drift between code and adjacent docstrings/READMEs.
- **`test-gap`** — surfaces untested branches and recently-changed
  uncovered code.

**Scope (DevEx).**
- A real terminal asciicast/GIF in the README produced by a maintained
  fixture (`scripts/record-demo`).
- An `examples/` directory:
  - Python final-PR profile;
  - TypeScript profile;
  - Rust or Go profile (one of);
  - triage-enabled profile;
  - commit-after-remediation profile;
  - hands-off CI profile (referenced from M8).
- Issue templates collect version, command, harness, artifact path,
  failure summary fingerprint.
- Three concrete `good first issue` candidates with acceptance criteria
  that don't require deep Codex internals.
- A "failure diagnostics guide" derived from the M2 schema and real
  launch findings.
- Shell completions (`bash`, `zsh`, `fish`) shipped via the package.

**Acceptance criteria.**
- New users can run a documented example in a disposable repository.
- Built-in expert profiles can be invoked directly
  (e.g., `revrem --profile security`).
- The expert-profile fixture suite shows ≥ 4 profiles producing
  distinct, non-redundant findings on a contrived multi-issue repo
  (≤ 20% finding overlap).
- README demo uses a real captured run or a maintained fixture.
- Issue templates collect version, command, harness, artifact path,
  failure summary fingerprint.
- ≥ 3 starter issues exist with clear acceptance criteria.

**Quality bar.** A developer who has never used the tool reads the
README, picks an expert profile, runs it on their own repo, and
recognises the findings as their *kind* of problem — not generic ones.

### Milestone 8 — Hands-Off CI Surface And Static Report

**Autonomy:** L3. **Theme:** Autonomy, Craft, Distillation.

**Goal.** Turn RevRem into something a team can drop into a CI pipeline
or a GitHub Action, with a rendered artifact a reviewer wants to read.

**Scope.**
- `revrem report <run-dir>` produces a self-contained static HTML page
  from `summary.json` + `events.jsonl` (no JS frameworks, just HTML +
  inline CSS). The page summarizes findings, triage, diff stats, checks,
  and cost. Suitable for CI artifact upload.
- A reference GitHub Action (`revrem-action`) in this repo or a sibling
  that:
  - installs `revrem` via pipx;
  - runs the configured profile against the PR head vs base;
  - uploads the run dir + HTML report as an artifact;
  - posts a single, idempotent PR comment summarizing findings,
    suppressions, cost, and a "rerun" hint;
  - respects branch policies and only escalates severity gates the
    repo owner has opted into.
- Documented patterns for using RevRem inside other CI systems
  (GitLab CI, Buildkite, generic shell). The Action is exemplary, not
  exclusive.
- Privacy contract: the Action never uploads artifacts off the repo's
  CI store unless the user wires their own integration.

**Acceptance criteria.**
- A reference repo opens a PR; CI runs the Action; a comment appears
  inside the metric target (≤ 5 min on a 1k-LOC PR).
- The HTML report is reproducible from a stored `events.jsonl` via
  `revrem report`.
- The Action is idempotent: re-runs do not stack comments.

**Quality bar.** A maintainer who only ever sees RevRem through a PR
comment thinks "I want this on every repo".

### Milestone 9 — Distillation Archive, Daemon, And Dataset Export

**Autonomy:** L3 → L4. **Theme:** Distillation, Autonomy.

**Goal.** Turn the per-run artifact stream into compounding evidence —
without compromising the local-first posture.

**Scope (archive).**
- Opt-in `--archive-diffs` (or `archive: true` in profile) keeps an
  indexed history mapping each finding fingerprint to:
  - original review excerpt;
  - triage classification;
  - suppression status;
  - applied diff (if any);
  - check outcome after remediation.
- Schema-versioned, stored under `~/.local/share/revrem/archive/` by
  default; per-repo override supported.
- **Privacy.** A configurable scrubber redacts paths matching
  `.gitignore`, files declared sensitive in profile config, and
  detected secrets via `detect-secrets`. Scrubbing is on by default.

**Scope (export).**
- `revrem archive export --format jsonl` produces a portable dataset
  (one record per finding/diff pair) suitable for consumption by
  HuggingFace `datasets`, RFT/DPO pipelines, or org dashboards.
- `--format parquet` if dependency footprint is worth it (gated extra).
- Documented schema in `docs/52-api/`.

**Scope (daemon — investigative).**
- `revrem watch` runs in the background, observes new commits on
  configured branches, and runs a bounded loop within declared cost
  ceilings, depositing artifacts into the archive.
- Daemon mode is opt-in, single-user, local; no networked control
  plane. It must be killable cleanly and survive SIGSTOP/SIGCONT.

**Acceptance criteria.**
- Archive entries pass schema validation and survive scrubbing tests
  (including a deliberately-poisoned fixture with synthetic secrets).
- Export produces a dataset that loads cleanly in HuggingFace
  `datasets`.
- `revrem watch` respects cost ceilings; a kill -9 leaves no orphan
  Codex processes (verified by test).

**Quality bar.** A user who runs RevRem for a month has a privacy-safe
dataset of "what my reviewer caught and how I fixed it" they can
plausibly share with a teammate or feed into a fine-tune — and they
trust it because they can read it.

## Cross-Cutting Tracks

These don't fit a single milestone but must thread through several.

### Cost & Budget Governance

Owned primarily by M4. Every milestone adding model invocations
(M3 triage, M6 secondary harness, M9 daemon) re-tests cost ceilings.
`summary.json` always reports observed totals; missing data is
explicit (`"tokens": null`), never silently zeroed.

### Determinism & Reproducibility

Pin model version, harness version, prompt version, and CLI version
into every `summary.json`. Replay (M4) is the test substrate. Where
the harness supports it, expose a `--seed`. Where it doesn't, say so
in `summary.json`.

### Privacy & Redaction

`detect-secrets` is already a dev dep; promote a thin wrapper to a
runtime helper used by M2 (bug bundles), M8 (CI comments), and
M9 (archive). Default to scrub-on-by-default everywhere user content
leaves the run dir.

### Plugin Surface (Late, Cautious)

Expose entry points (`revrem.harnesses`, `revrem.checks`,
`revrem.renderers`) only after their respective contracts are stable.
M6 ratifies the harness contract; checks and renderers follow only if
real demand emerges. Don't ship a plugin API for the imagined plugin.

### Security Hygiene

Branch protection, Scorecard, sigstore (M0/M1) are baseline. Audit
subprocess invocations for shell-injection surface; document the
sandbox posture explicitly in a `SECURITY.md` extension. Run
`pip-audit` / `osv-scanner` in CI; fail on known-exploitable CVEs.

## Hands-Off Threat Model

Hands-off operation is the product's most valuable and most dangerous axis.
The threat model is intentionally local-first but still serious.

### Assets

- User source code and repository metadata.
- Model prompts, review outputs, remediation diffs, and check output.
- Local run history and archive datasets.
- Git credentials indirectly reachable through the user's shell environment.
- CI tokens and PR comment permissions for GitHub Action mode.

### Adversaries And Failure Modes

- **Prompt/output injection from repository content.** A file can ask the model
  to ignore instructions, exfiltrate data, or modify unrelated paths.
- **Command injection through user-configured checks.** Checks are shell
  commands by design; the product must make that explicit and never synthesize
  unsafe shell fragments from model text.
- **Secret leakage through artifacts or bug bundles.** Logs can contain tokens,
  paths, or proprietary code excerpts.
- **Autonomous overreach.** A loop can spend too much money, rewrite too much
  code, or keep re-raising known false positives.
- **CI permission drift.** A GitHub Action can accidentally receive broader
  token permissions than needed.
- **Backend drift.** A provider CLI can change non-interactive semantics,
  sandbox defaults, or output format.

### Required Controls

- Model text is never executed as shell without an explicit operator-authored
  command boundary.
- Remediation is constrained by sandbox, worktree preflight, iteration count,
  wall-clock, and cost budget.
- Bug bundles, CI comments, and archives use scrub-on-by-default redaction.
- Suppressions are visible artifacts, not silent filters.
- GitHub Action permissions are least-privilege and documented per event type.
- Every harness declares capabilities and unsupported features before a run.

Any milestone that weakens these controls must add an ADR or update this plan
before implementation.

## Risks & Assumptions Register

| ID | Risk / assumption | Likelihood | Impact | Mitigation | Owning milestone |
|---|---|---:|---:|---|---|
| R1 | Codex CLI changes its non-interactive contract | Med | High | Pin a tested Codex version range; harness contract (M6) abstracts away | M6 |
| R2 | ~~PyPI naming for `revrem` unavailable~~ Resolved: `revrem` confirmed as published name | ~~Low~~ N/A | ~~Med~~ N/A | Plan B no longer needed; name secured in M1 | ~~M1~~ Closed |
| R3 | Triage produces confident false negatives that suppress real bugs | Med | High | Labelled fixture set + precision metric ≥ 0.85; rejected findings carry rationale and stay in artifact | M3 |
| R4 | Cost ceilings undercount due to harness-reported token gaps | Med | Med | `null` not `0`; document gap; CI fails when target harness's ceiling test underreports | M4 |
| R5 | TUI complexity outpaces test coverage | Med | High | Pilot tests gating each new screen; replay-only screens until events stabilise | M5 |
| R6 | Secondary harness maintenance burden | Med | High | Single secondary at a time; harness contract tests catch contract drift early | M6 |
| R7 | Archive grows unboundedly | High | Low | Default rolling cap (count + bytes); export-and-prune workflow | M9 |
| R8 | Privacy regression in archive/export | Low | Critical | Scrub-on-by-default; poisoned-fixture tests; explicit opt-in to disable scrub | M9 |
| R9 | Daemon mode encourages unbounded autonomous behavior | Med | High | Cost ceilings mandatory in `watch`; refuse to start without them | M9 |
| R10 | Roadmap scope outruns single-maintainer capacity | High | Med | Tracks A/B/C are independent; each milestone is independently shippable | All |

## Versioning & Stability Path To 1.0

| Version | Boundary | Stability commitments |
|---|---|---|
| 0.4.0 | M0 + M1 done | `revrem --version`, `revrem` CLI surface considered stable for documented flags; artifact dir layout stable. |
| 0.5.0 | M2 + M3 done | Artifact schema v1 frozen; suppressions file format stable; `summary.json` shape additive-only. |
| 0.6.0 | M4 done | Event schema v1 frozen; `events.jsonl` is a public contract; replay supported across patch versions. |
| 0.7.0 | M5 done | Hook entry points and headless exit codes stable. |
| 0.8.0 | M6 + M7 done | Harness contract v1 frozen; bundled expert profiles stable surface area. |
| 0.9.0 | M8 done | CI surface and HTML report layout stable. |
| 1.0.0 | M9 done; metrics in §"Success Metrics" met | Public API surface (CLI flags, profile schema, artifact schema, event schema, harness contract, suppression format, archive schema) frozen under SemVer. |

A 1.0 release implies "this tool is now boring infrastructure" — every
listed contract changes only with a major version bump.

## Parallel Work Tracks (Replaces Linear PR Sequence)

Three tracks run concurrently after M0 lands. Within a track, PRs are
serial. Across tracks, they are independent.

```text
Track A (Trust):    M0 ──> M1 ──> M2 ───────────────────────────────> 1.0
Track B (Workflow):       M3 ──> M4 ──> M5 ─────────────────────────> 1.0
Track C (Showcase):              M6 ──> M7 ──> M8 ──> M9 ──────────> 1.0
                             (M0 unblocks B; M3 unblocks C)
```

Indicative PR list (each scoped to one or two themes; "atomic unit of
work" still means code + tests + docs + verification evidence):

1. **PR A.0** — public-project cleanup (M0).
2. **PR A.1** — packaging + TestPyPI + provenance + install matrix (M1).
3. **PR A.2** — `revrem doctor` + diagnostics schema v1 (M2 split 1/2).
4. **PR A.3** — artifact schema doc + bug-bundle + history hardening (M2 split 2/2).
5. **PR B.0** — triage contract + `triage.json` + remediation handoff (M3 split 1/2).
6. **PR B.1** — suppressions file + `revrem suppress` CLI (M3 split 2/2).
7. **PR B.2** — event sink + `events.jsonl` + replay (M4 split 1/2).
8. **PR B.3** — cost ceilings + cancellation + resume (M4 split 2/2).
9. **PR B.4** — TUI runs (M5 split 1/2).
10. **PR B.5** — hooks + headless mode (M5 split 2/2).
11. **PR C.0** — harness contract + fake harness (M6 split 1/2).
12. **PR C.1** — secondary adapter (Claude CLI) (M6 split 2/2).
13. **PR C.2** — expert profiles bundle + asciicast + examples (M7).
14. **PR C.3** — `revrem report` static HTML + GitHub Action (M8).
15. **PR C.4** — archive + privacy scrubber + dataset export (M9 split 1/2).
16. **PR C.5** — `revrem watch` daemon (M9 split 2/2).

PRs may merge out of intra-track order if dependencies have already
landed; the numbering is a recommendation, not a constraint.

## Operating Gates

Every roadmap PR preserves the repository's atomic unit of work:

- code;
- tests;
- public docs *or* governed docs;
- local verification evidence (paste in PR body).

Minimum verification:

```bash
./scripts/dev-check
pre-commit run --all-files
git diff --check
```

Additional gates by area:

- **Packaging** — `python -m build`, `twine check`, fresh-venv install
  smoke on Linux and macOS runners.
- **Schema changes** — schema validation on all fixture artifacts;
  diff against the previous schema version with explicit
  additive/breaking classification.
- **TUI** — Textual dependency-gated tests plus Pilot coverage for
  every changed screen; replayable from event fixtures.
- **Harnesses** — fake harness contract tests plus one real smoke run
  per supported harness where feasible.
- **CI surface** — Action smoke on a reference PR in a sibling repo.
- **Privacy/archive** — poisoned-fixture redaction tests must pass.
- **Release workflow** — GitHub Actions runs on a tag in a non-prod
  dry-run or TestPyPI stage before PyPI; provenance attached.

## Open Questions (Tracked Separately)

These don't block the roadmap but should be resolved before the
relevant milestone closes:

- **OQ1 (M1).** ~~Is `revrem` available on PyPI?~~ Resolved: `revrem` is the
  published name; `code-review-loop` is retained as the distribution alias.
- **OQ2 (M3).** Should suppressions be repo-local (committed) or
  user-local (`~/.local/share/revrem/`)? Default likely committed
  for team workflows; user-local is opt-in.
- **OQ3 (M4).** Do we adopt an existing event schema convention
  (e.g., CloudEvents) or stay bespoke? Bespoke favours simplicity;
  convention favours interop.
- **OQ4 (M6).** Order of secondary harnesses: Claude CLI vs Gemini
  CLI vs `aider`-style agentic harness?
- **OQ5 (M8).** Should the GitHub Action live in this repo or its own?
  Own repo is cleaner for marketplace listing; this repo is fewer
  moving parts.
- **OQ6 (M9).** Archive default location: per-user vs per-repo? And
  do we offer a `revrem archive prune` policy out of the box?

## Progress Audit Snapshot

This roadmap is **partially complete**, not closed. Its status remains
`Approved` because it is the accepted governing roadmap, but substantial
milestone work remains before the roadmap itself can be considered complete.

| Milestone | Current state on 2026-06-01 | Audit status |
|---|---|---|
| M0 — Public Trust Baseline | Covered by `REVREM-TASK-001`; public repository, launch PR history, CI/release/community files, and DocOps checks are in place. | Completed |
| M1 — Install And Release Distribution | Covered by `REVREM-TASK-002`; package metadata, wheel/sdist smoke, release workflow, provenance/checksum path, rollback runbook, and `v0.3.2` release evidence exist. | Completed |
| M2 — Runtime Hardening, Diagnostics, And Schema | Covered by `REVREM-TASK-002`; `revrem doctor`, diagnostics, schemas, bug bundles, fingerprints, and fixture validation exist. | Completed |
| M3 — Triage Productization And Suppressions | Covered by `REVREM-TASK-002`; triage artifacts, structured handoff, suppressions, suppression CLI, audit/redaction behavior, and tests exist. | Completed |
| M4 — Event Stream, Cost Governance, And Replay | Covered by `REVREM-TASK-002`; `events.jsonl`, replay fixtures, budget/cancellation/resume tests, and stable exit-code coverage exist. | Completed |
| M5 — TUI Runs, Hooks, And Headless Mode | Headless application boundary exists from `REVREM-TASK-003`, but real TUI-launched runs, hook installation/examples, check discovery, and full resume equivalence remain open. | Remaining work |
| M6 — Harness Contract And Non-OpenAI Backends | Fake harness and thin Codex/Claude/Gemini/opencode/Kilo command adapters exist via `REVREM-PLAN-004`; `REVREM-TASK-006` records provider-gated live smoke coverage, missing-auth classification, and a successful credentialed Gemini routed-remediation smoke with routing artifacts. | Completed |
| M7 — Expert Profiles And Public DevEx Expansion | No bundled expert-profile suite, examples matrix, shell completions, or maintained demo asset are present. | Remaining work |
| M8 — Hands-Off CI Surface And Static Report | No `revrem report` static HTML command or GitHub Action/PR-comment surface is present. | Remaining work |
| M9 — Distillation Archive, Daemon, And Dataset Export | No archive export/dataset surface or `revrem watch` daemon is present. | Remaining work |

Near-term governing follow-ups are therefore M5, then M7-M9. Completed
TASK-001 through TASK-004, the first slice of PLAN-004, and TASK-006 do not
close the whole roadmap.
