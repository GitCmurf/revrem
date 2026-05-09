---
document_id: REVREM-PLAN-003
type: PLAN
title: Post-Launch Development Roadmap
status: Draft
version: '0.1'
last_updated: '2026-05-09'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Prioritized hardening and feature roadmap after the first public RevRem
  launch
keywords:
- revrem
- roadmap
- hardening
- devex
- distribution
related_ids:
- REVREM-PRD-001
- REVREM-PLAN-002
- REVREM-DEVEX-001
- REVREM-TEST-001
- REVREM-TASK-001
---

# PLAN: Post-Launch Development Roadmap

## Context

RevRem has completed its first public GitHub launch. The next work should move
from launch mechanics to public-project trust, adoption friction, and the
operator workflow quality that differentiates the tool.

The key product question is not whether to build "more features" immediately.
The highest-value next work is the sequence that makes a skeptical external
developer able to:

1. understand the tool quickly;
2. install it safely;
3. run a bounded loop with predictable artifacts;
4. trust failures and diagnostics;
5. grow into richer triage, UI, and backend options without changing the core
   workflow.

This plan ranks candidate investments after the public launch: triage stage,
GUI/TUI, PyPI distribution, non-OpenAI model support, and adjacent hardening.

## Content

## Recommendation

Prioritize the roadmap in this order:

1. **Distribution and release trust.** Make installation, releases, and public
   repository hygiene boring and reliable. This has the biggest external DevEx
   payoff because every new user hits it before they can evaluate the loop.
2. **Operational hardening and diagnostics.** Keep investing in preflights,
   timeout behavior, artifact quality, and failure summaries. RevRem is a tool
   for watched automation; trustworthy failure modes are core product value.
3. **Triage as a first-class workflow.** The triage stage is already aligned
   with how operators use review findings. Promote it from optional plumbing to
   a documented, tested, review-quality feature before adding more UI surface.
4. **Event-stream foundation for GUI execution.** Build the event interface
   that lets CLI, Rich progress, run history, and TUI consume the same loop
   events. This is more important than drawing more screens.
5. **Non-OpenAI backend adapters.** Defer real Claude/Gemini/opencode support
   until the harness contract is stable and testable with a fake backend. Model
   breadth is valuable, but adding it too early multiplies failure modes.

PyPI is therefore the highest-value feature-development item. Triage is the
highest-value workflow feature. GUI execution and non-OpenAI models should come
after the shared execution contracts are hardened.

## Decision Matrix

| Candidate | User value | Risk | Dependency | Recommended priority |
|---|---:|---:|---|---:|
| PyPI / release distribution | High | Medium | Release workflow, metadata, provenance | P0 |
| Failure diagnostics and preflights | High | Low | Existing CLI runner | P0 |
| Triage stage productization | High | Medium | Prompt contract, artifact schema | P1 |
| Public DevEx polish | High | Low | README, issues, examples | P1 |
| Event stream for loop lifecycle | High | Medium | Progress/history contracts | P1 |
| TUI starts real runs | Medium | High | Event stream, cancellation semantics | P2 |
| Non-OpenAI adapters | Medium | High | Harness contract, config schema | P2 |
| Web/hosted GUI | Low | High | Product strategy change | Defer |

## Milestone 0: Public Trust Baseline

### Goal

Finish the post-launch public-project baseline so the repository does not look
half-published or internally oriented.

### Scope

- Ensure the default branch, branch protection, security policy, CI badges, and
  release page all reflect the public `main` branch.
- Add issue templates and labels for `bug`, `enhancement`, `docs`, `debt`,
  `good first issue`, and `help wanted`.
- Confirm Dependabot version updates target `main` and old launch PRs are
  closed rather than merged.
- Add a fresh `main` push after default-branch correction so Scorecard evaluates
  a valid event payload.
- Keep the README external-facing and keep internal release checklists in
  contributor or governed docs.

### Acceptance Criteria

- GitHub shows `main` as the default branch and only expected long-lived remote
  branches remain.
- CI is green on `main`.
- Branch protection requires the Python CI checks before merge.
- Security policy and dependency alerts are enabled.
- README badges resolve to real, green, public targets.
- `./scripts/dev-check` passes locally.

## Milestone 1: Install And Release Distribution

### Goal

Make `revrem` installable and updatable through a standard external path while
preserving the repo-local dev/stable workflow used by the maintainer.

### Scope

- Decide package identity before PyPI publication:
  - keep `code-review-loop` as the distribution name and document `revrem` as
    the command; or
  - reserve/publish `revrem` if package naming is available and governance
    allows the migration.
- Add a release checklist document outside the README, or promote the existing
  contributor release guidance into a dedicated governed release plan.
- Harden package metadata: description, URLs, classifiers, project keywords,
  optional extras, license expression, README rendering, and long-description
  validation.
- Add a build/check workflow for source distribution and wheel artifacts.
- Publish to TestPyPI first, then PyPI.
- Document installation modes:
  - `pipx install ...` for normal users;
  - `pip install ...` for controlled environments;
  - source checkout plus `./scripts/install-dev` for contributors;
  - `./scripts/promote-stable` for the maintainer's local multi-repo workflow.

### Acceptance Criteria

- `python -m build`, `twine check`, and package smoke tests pass in CI.
- TestPyPI install works in a fresh virtual environment.
- PyPI install or `pipx install` exposes `revrem --version`.
- Release artifacts have provenance/SBOM coverage where the workflow supports
  it.
- README install section is updated only after the package is actually
  published.

### Why This Comes Before GUI

External users cannot benefit from a richer GUI if installation still requires
cloning the repository and trusting local scripts. Distribution is the first
conversion bottleneck.

## Milestone 2: Runtime Hardening And Diagnostics

### Goal

Make failure modes fast, local, and self-diagnosing. RevRem should never leave
an operator wondering whether the model is thinking, the CLI is wedged, or the
repository state is invalid.

### Scope

- Keep and expand review-base preflights:
  - invalid base;
  - no merge base;
  - dirty worktree with commit mode;
  - missing Codex executable;
  - Codex auth/config not usable;
  - check commands not found.
- Add a `revrem doctor` or `revrem preflight` command for target repositories.
- Improve timeout artifacts with:
  - command;
  - cwd;
  - elapsed time;
  - process-group cleanup result;
  - partial stdout/stderr;
  - likely remediation hints.
- Add an artifact schema/version field for summaries and diagnostic files.
- Add compact bug-report bundles for failed runs, excluding secrets and local
  transcripts by default.
- Ensure run history remains append-safe under interruption and read-safe under
  truncation.

### Acceptance Criteria

- Common invalid setup states fail before launching Codex.
- Every failed phase writes an artifact and summary.
- Timeout tests cover direct children and pipe-holding descendants.
- `revrem preflight --format json` is stable enough for agents and CI.
- `REVREM-TEST-001` includes the new failure-mode test matrix.

## Milestone 3: Triage Stage Productization

### Goal

Turn triage from an optional intermediate pass into a reliable way to separate
true findings, false positives, implementation order, and verification
requirements before remediation.

### Scope

- Define a triage artifact contract:
  - confirmed actionable findings;
  - likely false positives;
  - risk/severity;
  - files/modules affected;
  - suggested implementation order;
  - required verification commands.
- Add `--triage` and profile defaults that are clear in help output and docs.
- Add structured triage output support for agent consumption.
- Feed triage output into remediation prompts without losing the original review
  context.
- Add tests for triage failure, timeout, false-positive handling, and
  prompt-size truncation.
- Add README and DevEx examples for "review -> triage -> remediate -> verify".

### Acceptance Criteria

- Triage can be enabled from CLI and profile config.
- Triage artifacts are linked from `summary.json`.
- Remediation receives triage guidance and original review excerpts.
- Invalid triage output fails safe rather than suppressing review findings.
- Documentation explains when triage is worth the additional model call.

### Why This Beats Immediate Non-OpenAI Support

Triage improves result quality for every backend. Additional model backends
increase reach, but without a strong triage and artifact contract they also
increase ambiguity.

## Milestone 4: Event Stream And TUI Execution Foundation

### Goal

Create one loop event model that can feed compact progress, Rich progress,
history, diagnostics, and the Textual TUI without duplicating execution logic.

### Scope

- Define typed events for phase start, phase output, phase result, status
  classification, check result, artifact write, warning, failure, and summary.
- Replace ad hoc progress calls with an event sink interface.
- Keep terminal output behavior stable by adapting current compact/Rich
  renderers to the event sink.
- Add cancellation semantics for long-running review/remediation/check phases.
- Add event-stream fixtures for TUI tests.
- Update `REVREM-PLAN-002` when the event foundation is ready to unblock real
  TUI-launched runs.

### Acceptance Criteria

- CLI output remains compatible with current tests.
- JSON event fixtures cover clear, findings, unknown, timeout, check failure,
  and cancellation paths.
- TUI can render a replayed run from event fixtures before it starts real runs.
- No second implementation of review/remediation execution exists.

## Milestone 5: TUI Run Execution

### Goal

Let the TUI start, monitor, cancel, and summarize real RevRem runs while
preserving CLI semantics.

### Scope

- Start runs from selected profiles.
- Show current phase, model, base branch, checks, elapsed time, and artifact
  paths.
- Support cancellation with terminal/process cleanup.
- Surface clear/findings/unknown/failure states distinctly.
- Link to latest review, remediation, checks, and summary artifacts.
- Keep "copy command" and "run in terminal" paths available for operators who
  prefer the CLI.

### Acceptance Criteria

- A TUI-launched run produces the same artifacts and summary as the equivalent
  CLI run.
- Textual Pilot tests cover launch, cancellation, and at least three failure
  states.
- TUI remains optional behind the `[tui]` extra.
- CLI remains the documented primary automation surface.

## Milestone 6: Harness Contract And Non-OpenAI Backends

### Goal

Support additional review/remediation engines without making the loop depend on
Codex-specific assumptions.

### Scope

- Define a backend/harness capability contract:
  - review command shape;
  - remediation command shape;
  - stdin/stdout behavior;
  - sandbox/write controls;
  - model configuration;
  - timeout/cancellation behavior;
  - structured output support;
  - unsupported feature reporting.
- Add a fake harness used by tests to prove the contract independent of Codex.
- Move Codex-specific status parsing behind a harness boundary where needed.
- Add one real secondary adapter only after the fake harness and docs are
  stable.
- Prefer a small first adapter with clear non-interactive behavior over a broad
  "any model" abstraction.

### Candidate Backend Order

1. **Codex remains primary.** It is the proven backend and should define the
   baseline behavior.
2. **Claude CLI or Gemini CLI only if non-interactive review and exec semantics
   are stable locally.** Do not add an adapter that requires interactive
   prompts or ambiguous approvals.
3. **OpenRouter/HTTP model APIs are not first choice.** They would require
   building more of the agent loop directly inside RevRem, which increases
   security and prompt-management burden.

### Acceptance Criteria

- Profiles can name supported and unsupported harnesses with clear validation.
- Fake harness test suite covers review, remediation, triage, timeout, and
  unsupported feature paths.
- A real secondary harness has documentation, examples, and failure diagnostics.
- Existing Codex behavior is not regressed.

## Milestone 7: Public DevEx Expansion

### Goal

Make RevRem easier to evaluate, learn, and contribute to after the core trust
and distribution work is complete.

### Scope

- Add a real terminal GIF/asciicast or screenshot asset to the README.
- Add a examples directory with:
  - Python final PR profile;
  - TypeScript profile;
  - triage-enabled profile;
  - commit-after-remediation profile.
- Add issue templates for bug reports and feature requests.
- Add `good first issue` candidates that do not require deep Codex internals.
- Publish a "failure diagnostics guide" based on real launch findings.
- Add shell completions if CLI usage grows.

### Acceptance Criteria

- New users can run a documented example in a disposable repository.
- README demo uses a real captured run or maintained fixture.
- Issue templates collect version, command, artifact path, and failure summary.
- At least three starter issues exist with clear acceptance criteria.

## Deferred Or Explicitly Lower Priority

### Hosted Web UI

RevRem's current product value is watched local automation. A hosted web UI
would add authentication, storage, secret handling, and privacy questions that
are not needed for the next adoption step.

### Automatic Unbounded Remediation

Keep unbounded loops explicit and discouraged. The safety model depends on
bounded execution and operator inspection.

### Full Model Marketplace

Do not build a broad provider abstraction until one additional backend has
proved the harness contract. The first goal is reliable local automation, not
maximal model routing.

## Suggested Sequence Of PRs

1. **PR A: Public project cleanup.**
   README follow-up, branch/ruleset docs, issue templates, labels, Scorecard
   refresh, and fresh main check.
2. **PR B: Packaging and TestPyPI.**
   Build checks, package metadata, TestPyPI publish workflow, installation
   docs, and fresh environment smoke tests.
3. **PR C: `revrem preflight`.**
   Target-repo doctor/preflight command with JSON output and diagnostic
   artifacts.
4. **PR D: Triage contract.**
   Structured triage artifacts, profile/CLI docs, and remediation handoff tests.
5. **PR E: Event sink.**
   Typed loop events, progress renderer adapters, history compatibility tests.
6. **PR F: TUI run execution.**
   Real run launch/cancel/monitor using the event sink.
7. **PR G: Harness contract.**
   Fake harness, backend capability schema, and one candidate secondary adapter
   spike behind an experimental flag.

## Operating Gates

Every roadmap PR should preserve the repository's atomic unit of work:

- code;
- tests;
- public docs or governed docs;
- local verification evidence.

Minimum verification:

```bash
./scripts/dev-check
pre-commit run --all-files
git diff --check
```

Additional gates by area:

- Packaging: `python -m build`, `twine check`, fresh-venv install smoke.
- TUI: Textual dependency-gated tests plus Pilot coverage for changed screens.
- Harnesses: fake harness contract tests plus one real smoke where feasible.
- Release workflow: GitHub Actions run on a tag in a non-production dry run or
  TestPyPI stage before PyPI.
