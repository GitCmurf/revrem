# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## [Unreleased]

## [0.5.0] - 2026-06-21

The "showcase & hands-off adoption" release: a static HTML report for finished
runs, headless/CI output hardening, and a reference GitHub Action that posts a
single updatable PR comment. Tier 1 of `REVREM-PLAN-005`; expert profiles
(Pillar C) and DevEx polish (Pillar D) are deferred to v0.5.x.

### Added

- `revrem report <run-dir>`: renders a finished run's `summary.json` +
  `events.jsonl` into a single self-contained HTML file (plain HTML5 + inline
  CSS, no JavaScript or external assets, safe to upload as a CI artifact and
  open offline). Never invokes a model or touches the network. Redacted by
  default; `--no-redact` requires `--i-understand-the-risks`. `--format json`
  prints a machine-readable index to stdout (the `--output` flag is ignored in
  that mode). Truncated or malformed events render what is available and warn
  rather than failing — the report is diagnostic.
- `report-index-v1` JSON schema: the frozen cross-boundary contract describing
  the machine index's fields and nullability (`cost_usd` null for dry-runs /
  fake harnesses; `top_findings` empty when none; `artifact_paths` empty when
  unavailable). Added with a `_history/` baseline.
- Reference GitHub Action (`action.yml`): runs a revrem profile on a pull
  request, uploads the redacted HTML report, and posts a single updatable PR
  comment. Composite action with inputs for base, profile, budgets, checks,
  comment/upload/fail-on-findings toggles, and install-mode (`pypi` |
  `local`). Runs revrem headless, discovers the run directory from the JSON
  `artifact_dir` on stdout, and maps the exit code last (after artifacts and
  comment land). Fork-PR safe and least-privilege.
- `--no-tty` flag: forces non-interactive (headless) output — suppresses ANSI
  escape sequences, progress spinners, and terminal-title writes on stderr.
  Auto-triggered when the `CI` environment variable is set (GitHub Actions,
  CircleCI, Travis, Jenkins), so a standard CI run needs no RevRem-specific
  flag. Also exposed as an additive profile key `[output] no_tty`.
- Finished-run fixture catalogue under `tests/fixtures/runs/<scenario>/` (8
  terminal-state scenarios: clear, findings_remediated, findings_remaining,
  timeout, check_failure, cost_ceiling, cancelled, all_suppressed), co-locating
  `summary.json` + `events.jsonl` for read-only consumers.

### Changed

- The recommended CI invocation is
  `revrem --no-tty --progress-style compact --summary-format json` — compact
  progress is line-oriented and greppable, and `--summary-format json` prints
  canonical `summary.json` to stdout for downstream tooling.

### Fixed (corrective, post-peer-review)

- Findings now render from their authoritative source
  (`triage-N.json::confirmed_findings`, keyed by `summary.artifact_paths.triage`)
  instead of an invented `status_classification` severity payload that does not
  exist in the engine. Before this, the findings section, `finding_counts`, and
  `top_findings` were empty on every real run and the PR comment reported zero
  findings. (P0-1)
- The GitHub Action now wires `GITHUB_TOKEN` via a `github-token` input
  instead of an unset `env.GITHUB_TOKEN`, so the PR comment step actually
  authenticates and posts. (P0-3; default-token handling refined below.)
- Checks now render from `summary.iterations[].checks[]` (the engine's record),
  with `check_result` events as a fallback.
- The PR comment deep-links the uploaded report artifact
  (`REVREM_ARTIFACT_URL`) rather than always linking the workflow run.
- Added `tests/test_report_real_findings.py` — a standing gate that renders a
  real-engine-shaped fixture (a `status_classification` payload of
  `{message, summary}` plus a `triage-N.json` with a confirmed finding) and
  asserts the finding surfaces. This gate exists because the initial T0 fixtures
  were hand-authored against the renderer's assumptions rather than the engine's
  contract, producing self-confirming green tests. Registered in REVREM-TEST-001.

### Fixed (corrective, second peer-review iteration)

- **Reverted the P0-2 removal of the "Phase configuration" section** — the
  premise was wrong. `summary.phase_config` *is* written on every run by
  `reporting.add_summary_contract_fields` (present on 106/156 local runs, all
  recent ones), carrying per-phase `harness`/`model`/`reasoning_effort` for
  `review`/`triage`/`remediation`/`commit_message`. Deleting the section dropped
  a section that renders real data on every run. The section is restored,
  filtered to the model-bearing phases (`checks`/`runtime` carry no
  harness/model and are skipped, not rendered as blank rows), and now also
  surfaces reasoning-effort, timeout, and sandbox.
- **Documented `phase_config` in `summary-v1.schema.json`** (additive,
  non-breaking; `additionalProperties` was already `true`). The undocumented
  schema/engine drift is what led P0-2 to wrongly conclude the key did not
  exist. History baseline updated.
- **Fixed the inert fork-PR guard** in `action.yml`: `head.repo.fork != 'true'`
  always evaluated true under GitHub Actions' type coercion (boolean→1,
  `'true'`→NaN), so the comment step never actually skipped on fork PRs. Now
  `== false`. (Pending live verification on a real fork PR.)
- Findings rendering now also surfaces triage `rejected_findings` and
  `needs_more_info`, which were silently dropped; the outcome section surfaces
  per-iteration `iterations[].review_status`.
- The PR comment now labels the artifact deep-link `[Report]` (it was
  mislabelled `[Run]` while pointing at the artifact); the workflow-run link is
  used and labelled `[Run]` only as a fallback.
- `findings_with_triage` fixture is now representative of a real run (carries
  `phase_config` + `external_review_coverage`/`invocation`/`phase_failures`/
  `phase_observations`/`triage_diagnostics` in their real shapes), closing the
  self-confirming-fixture gap for the renderer paths under gate.

### Security & robustness (corrective, external review)

- **Script-injection hardening** in the reference Action: every workflow input
  is passed through `env:` and read as a shell variable, never interpolated as
  `${{ inputs.x }}` into a `run:` script (the latter is expanded into the script
  text before bash parses it). Budget inputs are validated as numeric; a test
  asserts no input is interpolated into any run script.
- **Token resolution** no longer depends on expression evaluation inside an
  input default: the `github-token` default is empty (not `${{ github.token }}`)
  and the comment step uses `${{ inputs.github-token || github.token }}`, so the
  fallback resolves the automatic token in the step context. A non-empty literal
  default would be truthy and silently defeat the fallback.
- **`raw-artifacts` honesty**: documented as uploading the run directory
  verbatim and **unredacted** (the prior "still-redacted" wording was false).
- **Report index** preserves array-valued `artifact_paths` (was flattening lists
  to repr strings) and redacts path values when `redact=True`.
- **PR comment** escapes Markdown table cells so a model-derived finding title
  containing `|`, a newline, or a backtick cannot break or inject formatting.
- **Dogfood Action workflow** now bootstraps Codex through
  `openai/codex-action@v1` before invoking RevRem, so GitHub-hosted runners
  have the `codex` executable/proxy that preflight requires. It also creates
  the repo-local `.venv` and passes explicit check commands for the dogfood
  gate, so preflight does not depend on tools that only exist on a developer
  workstation. The Action now has a constrained `routing` input for CI jobs
  that need to force routing on/off, and setup failures print the latest
  preflight `diagnostics.json` when RevRem writes one. The credentialed dogfood
  job skips fork PRs where provider secrets are intentionally unavailable.

### Stability

- **Frozen** (additive-only within v1): the artifact JSON schemas (`summary-v1`,
  `events-v1`, `report-index-v1`, and the others under `docs/52-api/schemas/`),
  the suppression-file surface, and the `summary.json` / `events.jsonl`
  artifacts.
- **Preview** (may change before the 0.9.0 freeze): the `revrem report` HTML
  layout and CSS are explicitly *not* a stable contract yet; only the
  `report-index-v1` fields are versioned. The expert-profile surface is
  deferred to v0.5.x and is also Preview.

### Deferred

- Pillar C (expert profiles T5–T7) and Pillar D (DevEx T8–T11) of
  `REVREM-PLAN-005` are deferred to v0.5.x follow-on releases.
- T12 (TUI launches real runs) is deferred to v0.6.0 per the plan's decision
  gate; the TUI keeps its current replay-from-events default.

## [0.4.0] - 2026-06-18

### Added

- Interactive CLI wizard: run `revrem` (or `revrem --wizard`) in a terminal to
  build a run command without memorising flags. It previews the exact provider
  CLI commands for each phase before any model call, with per-phase model,
  reasoning effort, and timeout selection. A stepping stone toward the planned
  TUI/GUI.
- Triage Stage upgrade to v2: enables deterministic routing, dynamic model
  selection, and structured handoffs between review and remediation phases.
- Routing Policy Engine: supports first-match rule sets based on domain tags,
  risk level, refactor depth, and module count.
- Deterministic safety signal detection: automatically detects sensitive
  keywords (auth, secrets, pii) in affected files to prevent de-escalation
  to cheaper models for high-risk changes.
- Multi-harness support: added thin CLI adapters for Claude, Gemini, OpenCode,
  and KiloCode to enable heterogeneous model routing.
- Remediation Prompt Composer: assembles prompts from deterministic fragments
  (e.g., engineering principles) and quoted triage drafts.
- `revrem policy lint --profile NAME`: validates routing configuration and
  rule logic without executing models.
- `revrem triage explain <run-dir>`: provides a human-readable explanation of
  how the policy engine resolved a specific routing decision.
- Triage v2 schema, routing-v1 schema, and routing-outcome-v1 schema added
  to the public API definition.
- OpenCode prompt-bearing phases now attach the saved prompt artifact with
  `opencode run --file` and emit a short positional instruction
  (`"Follow the attached RevRem prompt exactly."`) immediately before
  `--file`, since live `opencode run` rejects an attached prompt artifact
  without an accompanying positional message or `--command`. The behavior
  described in the `Changed` entry below is the canonical contract; the
  earlier "instead of using stdin" wording was superseded once the
  positional message was added. Model subprocesses also emit five-minute
  `waiting` progress diagnostics while they remain active.
- Kilo prompt-bearing phases now deliver the prompt via stdin instead of as a
  positional argv token, aligning Kilo with the Claude contract and matching
  the hermetic harness-adapter test that covers the stdin path. Gemini
  prompt-bearing phases use Gemini CLI's `--prompt` option for bounded
  prompts because live dogfood showed long-running stdin review invocations
  could hang until RevRem's subprocess timeout, while direct `gemini --prompt`
  probes completed successfully.
- External review harness subprocesses now classify common provider failures
  in operator errors and retry one transient provider-side review failure
  before failing the phase. Commit-message drafting now rejects explanatory
  model prose as an invalid subject, prefers a saved `commit-N-message-subject`
  sidecar when available, and falls back to the deterministic subject builder
  when the model output is not a usable subject. RevRem-enforced subprocess
  timeouts are classified as non-transient provider timeouts and are not
  retried.
- Prompted external review coverage is now recorded in `summary.json` as
  `external_review_coverage`, including generated context size, sent prompt
  size, delivery mode, truncation state, and truncation policy. Operators can
  set `--external-review-truncation-policy fail` or
  `runtime.external_review_truncation_policy = "fail"` to stop before a
  non-Codex review provider receives a truncated review prompt, and
  `--save-profile` preserves that fail-closed setting.
- `revrem checks suggest` now inspects repository markers without executing
  commands and returns structured check suggestions for profile authoring,
  including source, phase, confidence, estimated cost class, and network/setup
  notes. The same advisory output is available through `revrem doctor checks`,
  and Git hook suggestions now resolve hooks in linked worktrees and `.git`
  file layouts.
- `revrem install-hooks` installs and removes bounded RevRem-managed
  pre-commit/pre-push hook examples, refusing to overwrite unmanaged hooks
  unless `--force` preserves a backup. Hook installation now resolves Git's
  hook path so linked worktrees and `.git` file layouts are supported, and
  never treats symlink targets as RevRem-managed hooks to overwrite.
- Run artifacts now include `invocation.json`, mirrored under
  `summary.invocation`, so operators can inspect the redacted argv, cwd, and
  RevRem environment overrides that launched a saved run.
- Native Codex review now enforces RevRem's read-only review contract by
  passing `sandbox_mode="read-only"` through `codex review` config, keeping the
  saved argv aligned with progress and summary sandbox metadata.
- Triage v2 now recovers misplaced per-finding `definition_of_done` string
  lists by moving them into `prompt_requirements.definition_of_done`, recording
  the repair in parsing warnings and `summary.triage_diagnostics` so routing
  artifacts are preserved for recoverable model drift.
- Triage v2 now recovers route proposals that encode an unbounded route timeout
  as JSON `null` or text `none`, normalizing the value to `timeout_seconds = 0`
  before schema validation and reporting the repair as an info-level triage
  note.
- The project-local default and dogfood routing profiles now escalate
  review-classification/security findings and explicit routing-policy or
  model-escalation safety signals to non-de-escalatable `codex-frontier` rules
  while keeping localised medium-risk operator workflow fixes on `codex-midi`.
- Routing artifacts now reserve `policy_override` for real disagreements
  between the model proposal and the effective route; matching proposals backed
  by a rule are recorded as `proposal_accepted` with the matched rule IDs.
- The wizard now treats an omitted Codex model as a valid provider-default
  configuration instead of blocking dry-run/run/save-profile actions as
  unresolved.
- The wizard now keeps the repaired `low` Codex triage effort when stale
  profiles contain `triage.reasoning_effort = "minimal"` and the operator
  chooses the profile/current effort option.
- CLI config building now fails before provider execution when triage or
  routing-specific flags are supplied while triage is disabled; operators must
  add `--triage` or remove those flags instead of silently running without
  triage.
- Codex review-status classification now recognizes all-scope clear prose such
  as "No actionable correctness, security, or maintainability issues were
  identified" even when provider stderr/control transcript text is appended.
- Terminal summaries now hide info-only fallback-fingerprint bookkeeping;
  `triage-*.json` and `summary.json` still retain those notes for auditability.
- Triage v2 routing guidance now keeps ordinary local timeout/config precedence
  fixes on the default route unless the review describes active cancellation
  failure, runaway execution, finding-hiding, security, or multi-phase safety
  impact.
- Review status diagnostics now distinguish `clear_phrase=used` from
  `clear_phrase=seen_not_used:<reason>` so findings that mention clear-sounding
  prose no longer produce misleading status-debug lines.
- Review artifacts that contain only provider stderr/control transcripts are
  now treated as `unknown` review output instead of findings, preventing
  transcript text from being passed into structured triage as a giant prompt.
- Routed remediation now treats an explicit CLI `--timeout-seconds` value as
  an upper bound for route timeouts, including routes saved with
  `timeout_seconds = 0`, and `revrem doctor` warns on disabled route timeouts.
- Remediation/check hardening now supports bounded inner remediation-check
  retries via `runtime.inner_check_retries` / `--inner-check-retries`. The
  dogfood profile enables one retry so post-remediation check failures can be
  fed directly back to remediation before spending another full review pass.
  The checks phase also starts with a worktree cleanliness check that fails on
  untracked non-artifact files left by remediation, and check timeout progress
  now reports timeout evidence instead of misleading signal names when the
  captured artifact contains RevRem's timeout marker. Summaries retain
  per-attempt check history under `iterations[].check_attempts` while keeping
  `iterations[].checks` as the latest attempt. Timeout-only check
  failures do not trigger the inner remediation retry, preventing provider
  quota spend on test-runtime budget issues that need an operator rerun or a
  larger check timeout instead of another model edit.
- `--initial-review-file latest` now orders compatible runs by run/review
  modification time, not only artifact directory name, and keeps the "newest
  clear run means start fresh" contract so older unresolved reviews are not
  revived after a later successful run. When current git state is available,
  runs without recorded git state are no longer considered compatible `latest`
  candidates. Retry-attempt transcripts such as `review-1-attempt-1.txt` are
  excluded from latest-review discovery, including when a summary lists them as
  review artifacts, so provider diagnostics cannot seed a restart remediation.
- Remediation prompt composition now treats route/profile prompt fragments as
  trusted configuration that still fails hard when missing, while
  triage-generated `required_fragments` are advisory: unresolved names are
  ignored with a visible prompt warning instead of aborting remediation. The
  triage v2 prompt now lists the built-in fragment allowlist and tells models
  not to invent names such as `bounded-execution`.
- Startup pending-review detection now looks for non-clear review feedback when
  `--initial-review-file` was not supplied. Interactive TTY runs prompt the
  operator to reuse the review, inspect more detail, start fresh, or cancel
  before any provider call; reviews from a different `HEAD`/base are offered
  with an explicit warning. Non-interactive runs ignore the candidate unless
  `--pending-review auto` is supplied, and `auto` only uses compatible
  candidates. `--pending-review ignore` always starts fresh, and explicit
  `--initial-review-file` remains authoritative.
- When an operator chooses pending review feedback from a different `HEAD`/base,
  RevRem now treats the run as stale-review validation. A read-only validation
  pass using the configured review harness/model runs before write-capable
  remediation; if it emits `REVREM_STALE_REVIEW_STATUS: resolved`, remediation
  is skipped and the loop reports `clear (stale_review_already_resolved)` after
  checks pass and the non-artifact Git status snapshot remains unchanged. If the
  validator emits `still_applies`, RevRem proceeds to normal remediation; if it
  emits `unknown` or fails, RevRem stops before remediation. Normal remediation
  runs still ignore the marker text unless the run is actually validating stale
  review feedback. Stale-validation status is now parsed only from the first
  `STALE_REVIEW_VALIDATION:` block in provider stdout before any `[stderr]`
  transcript; echoed prompt templates or review context cannot override the
  validator's answer, and conflicting `status:`/marker values fail closed as
  `unknown`.
- Transient provider retry attempts and backoff are now runtime settings
  preserved in summaries and continuation commands. Defaults remain two
  attempts with one second of backoff, while the project-local dogfood profile
  uses three attempts with five seconds of backoff for watched expensive runs.
  Provider model availability errors such as OpenCode `Model not found` are now
  classified before generic server-error wrappers and are not retried.
- Commit-message drafting now detects repository mutations by read-only
  commit-message harnesses. If the harness already committed the staged patch
  and left the repository clean, RevRem adopts that commit, records
  `commit-N-message-side-effects.json`, and prints a warning that the model or
  harness is unsuitable for commit-message drafting; unsafe HEAD/index
  mutations still fail.
- Gemini Pro review runs now get a larger model-aware external review input
  cap when no CLI/profile cap is set, and prompted review progress now reports
  whether the supplied context is full or truncated. The Gemini Pro default
  stays below the current Gemini `--prompt` delivery guard so model-aware
  defaults do not create local argv-delivery failures. Long-running external
  review subprocesses add a stronger non-terminating waiting diagnostic after
  the configured quiet threshold.
- Public GitHub launch materials: README, contribution guidance, security
  policy, support policy, issue templates, pull request template, CODEOWNERS,
  NOTICE, CI hardening, Scorecard workflow, and release provenance/SBOM
  workflow.
- Release workflow dry-run controls, TestPyPI/PyPI Trusted Publishing routing,
  tag/version validation, SHA-256 checksum generation, Sigstore signing, and
  `REVREM-RUNBOOK-001` rollback guidance.
- Reference fixture repository for the post-launch foundation phase, with
  expected seeded findings and regression coverage to keep future profile,
  diagnostics, triage, and event work aligned.
- `revrem doctor` setup diagnostics for validating Git base refs, artifact
  writability, Codex availability, and check executables before the first model
  call.
- Shared finding fingerprint module and ADR-backed v1 algorithm for future
  diagnostics, triage, suppressions, bug bundles, and event schemas.
- Artifact helper for canonical JSON serialization, atomic writes, and
  run-directory path-safety checks.
- Initial `docs/52-api/schemas/` JSON Schema namespace with concrete
  diagnostics validation and reserved v1 skeletons for summary, triage, events,
  and bug bundles.
- `summary.json` now carries the v1 artifact envelope fields and is validated
  against `summary-v1.schema.json`.
- Added golden artifact scenario fixtures for clear, findings, setup-failure,
  timeout, check-failure, and unknown-review runs.
- Added `REVREM-ADR-004` for artifact schema v1, canonical JSON, atomic writes,
  and schema compatibility policy.
- Built-in redaction helpers for bug-report bundles, covering common API keys,
  authorization headers, private keys, sensitive environment assignments, home
  paths, and usernames.
- `revrem bundle-bug-report` creates deterministic redacted support bundles
  with manifest schema validation and raw-transcript opt-in.
- Added `REVREM-ADR-005` for redaction defaults and bug-report bundle privacy
  policy.
- Structured triage v1 support: JSON triage output is schema-validated, written
  to `triage-N.json`, and forwarded to remediation with original review context;
  invalid structured triage writes diagnostics and fails safe.
- Added `REVREM-ADR-006` for structured triage artifacts and invalid-output
  remediation policy.
- Commit hook failures in `--commit-after-remediation` mode now default to a
  bounded remediation retry, with configurable `stop` and explicit `no-verify`
  policies.
- `revrem suppress add|list|remove|expire|check` manages explicit finding
  suppressions, with audit logs, critical-finding guardrails, and
  structured-triage integration.
- Added `REVREM-ADR-007` for the suppression file and CLI contract.
- Suppression files are schema-tested, `revrem doctor` now warns about stale
  suppression entries, and bug-report bundles include redacted suppression
  audit summaries by default.
- Added the event envelope model, JSONL event sink/reader, compact offline
  `revrem replay`, and `REVREM-ADR-008` for the event/replay contract.
- Loop verification checks now emit explicit `check_result` events with
  command, status, return code, and artifact metadata.
- Phase-start events now include exact argv and prompt delivery/size metadata
  for provider debugging, with compact terminal summaries for external harness
  calls. They also carry a self-describing `payload_schema_version: "1.1"`
  field so external replay/diff tools can detect the richer payload shape
  without relying on event-envelope `schema_version` bumps.
- Replay fixtures now cover clear and fully suppressed runs, and warning
  progress statuses map to first-class `warning` events.
- Loop failure paths now emit structured `failure` events with stable reason
  payloads before writing the final summary.
- Added an asynchronous `RendererSink` event adapter so live renderers can
  consume sequenced events without blocking model/check execution.
- Run-monitor TUI state now derives event summaries from `events.jsonl`,
  including truncated and invalid stream diagnostics.
- Run summaries now emit `artifact_write` events for public artifact paths so
  replay/report consumers can discover artifacts from the event stream.
- Added initial budget ceilings: `--max-wall-seconds`, `--max-tokens`,
  `--max-usd`, `--soft-warn-fraction`, profile `[budgets]` defaults,
  wall-clock soft warnings, and exit code `3` for pre-model-call ceiling hits.
- Ctrl-C/SIGTERM cancellation now emits `cancellation`, writes run artifacts,
  restores terminal display state, and exits with stable code `5`.
- Added the v1 harness capability contract, JSON Schema, Codex capability
  metadata, and an explicit `REVREM_ALLOW_FAKE_HARNESS=1` gate for the future
  deterministic fake harness.
- Added the gated fake harness runner and fixtures for clear review,
  findings/remediation, and structured triage contract tests without Codex.
- Added a fake-vs-Codex summary structural-equivalence regression for the
  clear-review fixture path.
- Fake harness fixtures now cover timeout, cancellation, and unsupported
  negative paths.
- Summaries now record resume-safety Git state: `HEAD`, base ref, base commit,
  merge base, and availability.
- Added `revrem resume <run-dir>` precondition validation with stable exit code
  `4` for unsafe resumes.
- `revrem resume` now continues from the latest review artifact after passing
  safety checks, rebuilding the loop from recorded `resume_config`.
- Harness-reported token and USD charges now emit `cost_charge`, accumulate in
  summary budgets, and enforce `--max-tokens` / `--max-usd` ceilings before the
  next model call.
- Replay fixture coverage now spans clear, remediated, rejected-finding,
  timeout, check-failure, cancellation, cost-ceiling, and suppressed scenarios.
- The fake harness now exposes deterministic token-charge fixtures so budget
  ceilings can be tested through the same `CommandResult` accounting path used
  by model harnesses.
- Doctor diagnostics now include stable `f1:` fingerprints derived from the
  shared fingerprint algorithm without embedding absolute worktree paths.
- Live CLI runs now execute the doctor diagnostics path before the first model
  call and fail with setup exit code `4` plus `diagnostics.json` when blocking
  preflight issues are found.
- Doctor diagnostics now warn on explicitly disabled profile timeouts and
  non-UTF-8 locales, and `scripts/dev-render-diagnostics` renders the
  source-derived diagnostic code table for docs updates.
- The release build backend is pinned to `setuptools==80.9.0` for reproducible
  package builds.
- Fake harness fixtures now cover partial remediation output that fails while
  preserving the remediation artifact.
- Package smoke CI now covers Linux and macOS on Python 3.11 and 3.12, and the
  packaging metadata exposes the optional `redaction` extra.
- Package smoke CI now selects a single built wheel and uses the workspace path
  for installed CLI checks instead of relying on directory depth.
- Schema v1 reference files now have `_history` baselines guarded by artifact
  schema tests.
- V1 artifact schemas now validate timestamp formats, summary collection item
  shapes, suppression timestamps, and suppressed-finding payload structure more
  tightly.
- Bug-report bundles now include sanitized profile/preflight snapshot artifacts
  when a run records them.
- Failed or timed-out structured triage commands now write
  `diagnostics-N.json` before the loop exits, keeping triage failures
  inspectable from machine-readable artifacts.
- Operator cancellation now writes `diagnostics.json` alongside `summary.json`
  and `events.jsonl`.
- Profiles now support `[suppressions] scope = "repo" | "user"` so teams can
  declare their expected suppression write policy alongside review settings.

### Fixed

- Codex review-status interpretation now preserves same-sentence contrastive
  security and maintainability findings after negated clear correctness prose,
  so wording like "no correctness issues, but there is a security risk" no
  longer lets the remediation loop stop as clear.
- Auto-commit runs now enforce the documented clean-start invariant before any
  provider call. If `--commit-after-remediation` is enabled and `git status
  -z --untracked-files=all` reports non-artifact changes at startup,
  RevRem exits with the dirty paths instead of later allowing `git add -A` to
  sweep pre-existing local edits into a remediation commit.
- The post-remediation worktree cleanliness check now parses `git status -z`
  output (NUL-delimited, no quoting) instead of the line-oriented `--porcelain`
  variant, so untracked files whose names contain spaces, backslashes, or
  embedded newlines are decoded verbatim before being forwarded to
  `git add --intent-to-add`. The previous line parser passed Git's C-style
  quoted form (`"a b"`, `"back\\slash"`) to `git add`, which made the
  pathspec miss the file and rejected legitimate remediation output as a
  clean-state violation.
- Auto-commit runs now re-check `HEAD` and non-artifact worktree status before
  the first remediation attempt for each review finding. If another process
  edits or commits during the review/triage window, RevRem preserves the review
  artifact and stops before spending remediation work on a stale checkout.
- The public and packaged triage v2 schemas now accept the optional
  `suppressed_findings` array that RevRem already writes to triage artifacts
  after applying suppressions, so schema-validating consumers no longer reject
  valid suppressed v2 triage artifacts.
- Stale pending-review reuse now has a resolved no-op stop path. If the
  validation remediation emits `REVREM_STALE_REVIEW_STATUS: resolved`, checks
  pass, and the commit phase has no staged changes, RevRem stops with
  `stale_review_already_resolved` and surfaces the validation output instead
  of repeating the old stale finding as `no_changes_after_remediation`.
- Auto-commit safety guards now treat artifact exemptions as path-boundary
  exact, so sibling paths such as `artifacts2/...` are not ignored when the
  artifact directory is `artifacts`.
- Successful auto-commits now refresh the expected `HEAD` even when RevRem is
  launched from a repository subdirectory or linked-worktree-style checkout
  where `.git` is not directly under `cwd`.
- Commit-message drafting now detects read-only phase side effects. Newly
  created non-artifact helper files are removed with a diagnostic artifact and
  deterministic fallback subject; modifications to existing paths abort the
  commit phase instead of committing contaminated state.
- The post-remediation worktree cleanliness check no longer blocks legitimate
  patches that add new files. Untracked non-artifact files are now marked with
  `git add --intent-to-add` so the upcoming `git add -A` in the commit phase
  can pick them up, instead of failing the check before the commit flow can
  stage them. Auto-commit mode already refuses to start from a dirty
  worktree, so non-artifact files that appear after remediation are treated as
  intentional remediation output. Known generated paths should be covered by
  `.gitignore` or `--artifact-dir`, and secrets or policy violations remain the
  responsibility of configured verification and commit hooks. Auto-staged
  paths are recorded in the check artifact for visibility, and any
  `git add --intent-to-add` failure surfaces the underlying git error so the
  operator can clean up by hand.
- The post-remediation worktree cleanliness check no longer mutates the git
  index during check-only runs. `git add --intent-to-add` is now gated on
  `commit_after_remediation`, so a normal verification run leaves the
  operator's index and worktree untouched. Auto-commit behavior is unchanged:
  untracked non-artifact files are still intent-added so the upcoming commit
  phase can pick them up. In check-only mode, the check passes and lists the
  remaining untracked paths in the artifact so the operator can decide how to
  handle them.
- Provider subprocess timeouts enforced by RevRem are classified as
  non-transient even when the subprocess emitted partial stdout before
  RevRem's `Command timed out after ...` marker.
- Inner-check retry events now emit schema-compatible `iteration` labels
  (e.g. `1.1`, `1.1.1`) on `phase_start` and `phase_result` events instead
  of the `1-retry-1` / `1-retry-1.1` strings the events-v1 schema used to
  reject, so runs that actually exercise `--inner-check-retries` once
  again produce `events.jsonl` artifacts that validate against
  `docs/52-api/schemas/events-v1.schema.json`. The on-disk artifact stem
  keeps the operator-visible `remediation-1-retry-1.txt` /
  `check-1-retry-1-2.txt` shape documented in the devex guide; the
  events-v1 schema was widened from one to up to two dotted sub-indices
  (`[0-9]+(\.[0-9]+){0,2}`) so check sub-iterations under a retry still
  fit the contract.
- A no-op remediation that ends with an `unknown` last review status now
  exits with `final_status: "unknown"` (exit code 2) instead of being
  reported as `final_status: "clear"` (exit code 0). The
  `stopped_reason` remains `no_changes_after_remediation`, and the
  `clear` and `findings` mappings for that reason are unchanged. This
  preserves the prior non-clear exit for the case where RevRem never
  received a clear review signal.
- Stale-review validation now reports `stale_review_already_resolved`
  only after verification checks pass and a deterministic non-artifact
  Git status snapshot remains unchanged. This avoids a redundant final
  provider call when the stale finding is already resolved, while still
  failing the run if validation output claims resolution but leaves
  tracked edits, untracked files, or check-time side effects behind.
- The post-remediation worktree cleanliness check now fails (exit
  code 1) when untracked non-artifact files remain in a non-auto-commit
  run, instead of reporting `check_failures: 0` while leaving the
  files outside the reviewed `git diff` patch. The check stdout now
  starts with `Worktree cleanliness check FAILED`, lists the untracked
  paths, and tells the operator to remove scratch files, stage
  legitimate new files explicitly, or re-run with `--commit` to let
  RevRem stage them. The git index is still untouched in check-only
  mode; auto-commit mode keeps auto-staging untracked files via
  `git add --intent-to-add`.

### Changed

- Triage v2 and commit-message prompts are stricter for weaker secondary
  models: the triage prompt now includes exact `estimated_blast_radius`
  key names plus minimal valid JSON examples, and the commit-message prompt
  explicitly requires one output line with no explanatory prose.
- Structured triage now normalizes review priority severities (`P0`-`P4`) to
  schema severities before validation, preserving strict failure for unknown
  labels while allowing dogfood routing to proceed on common review output.
- Structured triage now also normalizes `needs_more_info.info_requested` values
  that are emitted as arrays of strings into a single newline-delimited string,
  and the v2 prompt clarifies fallback fingerprints for uniquely identifiable
  review comments without stable `f1:` IDs.
- Added a small captured-triage verification helper for replaying priority
  normalization evidence without shell heredocs or fragile pasted Python
  one-liners.
- Deterministic commit-message fallback subjects now strip repeated trigger
  verbs, avoid filename-derived scopes, and use deeper `src/code_review_loop`
  package scopes.
- README rewritten as the public project entry point.
- Package metadata now uses `revrem` as the public distribution identity while
  retaining `code-review-loop` as a compatibility console command.
- CI now builds the `revrem` wheel, validates package metadata, and smoke-tests
  the installed wheel on Linux and macOS.
- Local development gate expanded to include `git diff --check`.
- The CM2 commit-skip path now maps a `skipped_no_changes` outcome to
  `final_status: "clear"` only when the most recent review was `clear`, and to
  `final_status: "findings"` only when the most recent review explicitly found
  findings. An `unknown` review with no staged remediation remains
  `final_status: "unknown"` so an inconclusive review cannot become a clear
  exit. `stopped_reason` remains `no_changes_after_remediation`. The summary
  `schema_version` was bumped from `"1.0"` to `"1.1"` so scripted consumers
  that diff the schema can detect the contract change without reading the
  CHANGELOG; the on-disk shape of the summary is otherwise unchanged.
- Returncode-1 review results are now parsed for explicit/structured review
  status before provider-failure keyword classification. This preserves valid
  review findings that mention provider-like text such as "rate limit" or
  "API key" instead of misclassifying them as review invocation failures.

### Security

- Added detect-secrets baseline enforcement, gitleaks launch-scan guidance, and
  GitHub security reporting instructions.

## [0.3.2] - 2026-05-14

Release cut for the post-launch foundation work merged into `main`. This
release packages the public install smoke, diagnostics, artifact schemas,
fingerprints, suppressions, events, triage, budgets, and fake-harness
contracts that now back the stable foundation line.
