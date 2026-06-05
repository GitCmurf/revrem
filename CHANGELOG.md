# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## [Unreleased]

### Added

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
- Remediation/check hardening now supports bounded inner remediation-check
  retries via `runtime.inner_check_retries` / `--inner-check-retries`. The
  dogfood profile enables one retry so post-remediation check failures can be
  fed directly back to remediation before spending another full review pass.
  The checks phase also starts with a worktree cleanliness check that fails on
  untracked non-artifact files left by remediation, and check timeout progress
  now reports timeout evidence instead of misleading signal names when the
  captured artifact contains RevRem's timeout marker.
- Gemini Pro review runs now get a larger model-aware external review input
  cap when no CLI/profile cap is set, and prompted review progress now reports
  whether the supplied context is full or truncated. Long-running external
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

### Changed

- Structured triage now normalizes review priority severities (`P0`-`P4`) to
  schema severities before validation, preserving strict failure for unknown
  labels while allowing dogfood routing to proceed on common review output.
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
  `final_status: "clear"` whenever the most recent review was `clear` **or**
  `unknown`, and to `final_status: "findings"` only when the most recent
  review explicitly found findings. Previously, an `unknown` review with
  no staged remediation left the run in `final_status: "unknown"`; the
  effective behaviour now treats a no-changes remediation as deterministic
  clear evidence regardless of the preceding review's parse outcome.
  `stopped_reason` remains `no_changes_after_remediation`. Operators who
  scripted around the old `unknown` final status should adjust to the new
  mapping. The summary `schema_version` was bumped from `"1.0"` to `"1.1"`
  so scripted consumers that diff the schema can detect the contract
  change without reading the CHANGELOG; the on-disk shape of the summary
  is otherwise unchanged.
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
