---
document_id: REVREM-LEDGER-003
type: LEDGER
title: Behaviour ledger for the cli.py re-engineering (REVREM-TASK-003)
status: Approved
version: '1.4'
last_updated: '2026-06-07'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: The reviewed, append-only record of every intentional observable-output change made while executing REVREM-TASK-003. Machine-contract changes (JSON summary, events.jsonl, exit codes) must appear here with a schema_version impact note; human-presentation changes are logged for traceability but are unconstrained.
keywords:
- revrem
- behaviour-ledger
- output-contract
- golden-master
- traceability
related_ids:
- REVREM-TASK-003
- REVREM-TEST-001
---

# Behaviour Ledger — REVREM-TASK-003

This file is the instrument behind **Contract C3** of `REVREM-TASK-003`. The
golden-master suite (Wave A2) detects every diff in observable output; each
diff must resolve to exactly one of:

- **(a) an intended change** — recorded as an entry below, *before* the
  snapshot is updated; or
- **(b) a CI failure** — an unintended regression, fixed rather than ledgered.

There is no silent third option.

## What must be ledgered

- **Machine contract** (migration-gated): JSON summary shape, `events.jsonl`
  schema/content, exit codes. Any change requires a `schema_version` bump, a
  `CHANGELOG.md` entry, and an entry here.
- **Human presentation** (unconstrained, logged for traceability only):
  terminal text, progress rendering, cosmetic ordering. Entry here is optional
  but encouraged when a change is large enough to surprise a reader.

## Entry format

```
### YYYY-MM-DD — <short title> (<wave/PR>)

- **Contract:** machine | human
- **What changed:** <observable difference>
- **Why:** <reason>
- **Before / After:** <snippet or snapshot ref>
- **schema_version impact:** <none | bumped X -> Y> (machine only)
- **CHANGELOG:** <link/anchor> (machine only)
```

## Entries

### 2026-06-07 — Block-local stale-validation status parsing

- **Contract:** machine + human
- **What changed:** stale-validation status is read only from the first
  `STALE_REVIEW_VALIDATION:` block in provider stdout before any `[stderr]`
  transcript. Echoed prompt templates or original review text outside that
  block cannot override the validator's status; conflicting `status:` and
  `REVREM_STALE_REVIEW_STATUS:` values are treated as `unknown`.
- **Why:** Dogfood showed a validator correctly emitted `still_applies`, but
  RevRem scanned the combined stdout/stderr transcript, found an echoed
  `REVREM_STALE_REVIEW_STATUS: resolved` template in stderr, and incorrectly
  reported `stale_review_already_resolved`.
- **Before / After:** before, any marker anywhere in the transcript could win.
  After, only the validation block controls the outcome, and ambiguity fails
  closed before remediation or clear.
- **schema_version impact:** none.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-07 — Read-only stale validation and model-unavailable fail-fast

- **Contract:** machine + human
- **What changed:** stale pending-review validation now runs a read-only
  provider pass before any write-capable remediation. `resolved` skips
  remediation and proceeds to checks, `still_applies` proceeds to normal
  remediation, and `unknown` or validation failure stops before remediation.
  Provider model availability failures such as `Model not found` are classified
  as non-transient before generic server-error wrappers.
- **Why:** Dogfood showed that a stale finding already fixed in the current
  checkout could still burn remediation calls and fail on an unavailable
  remediation model. The OpenCode error included both `Model not found` and an
  `UnknownError` envelope, so generic server-error retrying was too broad.
- **Before / After:** before, validating an older review always invoked the
  remediation harness, and model-unavailable output could be retried as a
  transient server error. After, resolved stale findings avoid remediation
  entirely, and unavailable models fail fast with a setup/config signal.
- **schema_version impact:** none. New artifacts and summary fields are
  additive.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-07 — Stale-validation no-edits guard and dogfood provider retry policy

- **Contract:** machine + human
- **What changed:** resolved stale-review validation now snapshots
  non-artifact `git status --porcelain=v1 -z --untracked-files=all` entries
  before validation and before returning clear. If remediation or checks change
  tracked or untracked non-artifact paths, RevRem fails instead of reporting
  `stale_review_already_resolved`. Runtime config now includes
  `provider_retry_attempts` and `provider_retry_backoff_seconds`; the dogfood
  profile sets them to `3` and `5.0`.
- **Why:** Dogfood showed that stopping immediately after a resolved marker
  could bypass the no-edits invariant and that watched OpenCode remediation
  loops benefit from a stronger retry policy without changing defaults for all
  users.
- **Before / After:** before, a resolved marker could clear even if the model
  edited files or checks left new non-artifact changes. After, the resolved
  marker clears only with passing checks and unchanged non-artifact status.
  Before, retry attempts/backoff were hard-coded. After, they are runtime
  settings preserved in summaries, resume config, and continuation commands.
- **schema_version impact:** none. Summary schema version is unchanged; retry
  settings are additive runtime/resume fields.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-07 — Stale-review resolved marker scoped to validation mode

- **Contract:** machine + human
- **What changed:** remediation output is now scanned for
  `REVREM_STALE_REVIEW_STATUS: resolved` only when the current run is actually
  validating intentionally reused stale review feedback. Normal remediation
  runs that quote that marker while fixing stale-review code no longer set
  `stale_review_resolved` or trigger the contradictory "resolved marker but
  produced changes to commit" invariant.
- **Why:** Dogfood remediation of stale-review logic included the marker text
  in ordinary remediation output. Because marker detection was not scoped to
  stale-validation mode, a successful normal commit was followed by a false
  `remediation_failed` outcome.
- **Before / After:** before, any remediation transcript containing the marker
  could make a normal commit fail after it had already been created. After,
  the marker is meaningful only for `initial_review_mode = "stale"` validation
  runs; normal remediation proceeds to commit/review as usual.
- **schema_version impact:** none. Summary/event schemas are unchanged; this
  narrows when an existing state flag is set.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-07 — Triage v2 info-request normalization and Gemini prompt-cap safety

- **Contract:** machine + human
- **What changed:** structured triage parsing now normalizes
  `needs_more_info.info_requested` values that arrive as arrays of strings into
  one newline-delimited string before schema validation, recording a parsing
  warning. The triage v2 prompt now explicitly requires a single string and
  tells models to use `review-comment:<1-based-order>` for uniquely identifiable
  review comments without stable `f1:` IDs. Gemini Pro prompted review defaults
  now use a 95k character cap when no CLI/profile override is supplied.
- **Why:** Dogfood with a weaker triage model showed it could emit multiple
  information requests as a JSON array despite the schema requiring a string,
  wasting remediation flow on an avoidable invalid-triage warning. A subsequent
  review also showed that raising Gemini Pro's default above the current
  `--prompt` delivery guard would abort locally before invoking Gemini.
- **Before / After:** before, `info_requested: ["a", "b"]` failed the v2
  schema and was ignored under `triage.on_invalid = "continue"`; after, it is
  accepted as `"a\nb"` with a parsing warning, while mixed arrays still fail.
  Before, Gemini Pro model-aware defaults could be configured above the 100k
  argv-delivery guard; after, the default remains larger than the normal 80k
  cap but below the guard.
- **schema_version impact:** none. The triage v2 schema is unchanged; this is a
  parser normalization and prompt/default hardening.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-06 — Auto-commit clean-start/in-run guards and triage suppression schema

- **Contract:** machine + human
- **What changed:** auto-commit runs now inspect `git status --porcelain
  --untracked-files=all` before any provider call and exit with a preflight
  error when non-artifact worktree changes already exist. They also re-check
  `HEAD` and non-artifact worktree status before the first remediation attempt
  for each review finding, stopping before remediation if the checkout changed
  during review/triage. Triage v2 schemas now allow the optional
  `suppressed_findings` array that RevRem writes after applying suppressions.
- **Why:** Dogfood showed that the post-remediation cleanliness check could
  pass while later `git add -A` swept unrelated pre-existing edits into a
  remediation commit. Operator discussion then highlighted the adjacent
  expensive-run case: a human or another agent might change the checkout while
  RevRem is reviewing, making the subsequent remediation stale. The same run
  also showed valid v2 triage artifacts with suppression metadata failing
  schema validation because the public and packaged schemas lagged the emitted
  artifact shape.
- **Before / After:** before, a dirty worktree could reach review/remediation
  and be staged by the commit phase; after, auto-commit mode fails before
  provider spend unless the initial non-artifact worktree is clean. Before, a
  concurrent edit or commit during review could still enter remediation; after,
  RevRem stops after preserving the review output and before remediation. Before
  `triage-v2.schema.json` rejected `suppressed_findings`; after, it validates
  artifacts that include an empty or populated suppression array.
- **schema_version impact:** none. The triage v2 schema was widened
  additively; `summary.json` and `events.jsonl` versions are unchanged.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-06 — Startup pending-review choice

- **Contract:** human
- **What changed:** when no explicit `--initial-review-file` is supplied,
  interactive TTY runs now check for non-clear review feedback before starting a
  fresh provider review. If a compatible candidate exists, RevRem offers to use
  it, show more detail, start fresh, or cancel. If only a candidate from a
  different `HEAD`/base exists, RevRem still offers it but warns about the
  mismatch. Non-interactive runs ignore the candidate unless
  `--pending-review auto` is supplied; `auto` uses only compatible candidates
  and `--pending-review ignore` always starts fresh.
- **Why:** Dogfood showed a run could produce useful review output and then fail
  during triage/remediation setup, leaving an expensive review unremediated.
  A watched local operator should be able to reuse that review without
  remembering `--initial-review-file latest`, while automation must not block
  on stdin.
- **Before / After:** before, a restart without `--initial-review-file latest`
  always spent a new review call. After, TTY restarts offer pending review
  feedback first, warning when it comes from a different checkout state, while
  explicit/non-interactive modes remain deterministic.
- **schema_version impact:** none.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-06 — Stale pending-review validation

- **Contract:** human
- **What changed:** when an interactive operator chooses pending review
  feedback from a different `HEAD`/base, RevRem records that choice as stale
  review validation. The remediation prompt now asks the model to first decide
  whether the finding still applies to the current checkout and to make no
  edits plus emit a compact `STALE_REVIEW_VALIDATION:` evidence block ending in
  `REVREM_STALE_REVIEW_STATUS: resolved` when it is already fixed. If checks
  pass and the commit phase finds no changes, the loop exits successfully as
  `clear (stale_review_already_resolved)` and the terminal summary shows the
  validation output rather than repeating the old review comment. If the model
  emits the resolved marker but produces changes that would be committed, the
  loop fails instead of accepting a contradictory validation.
- **Why:** Dogfood showed that reusing an incompatible pending review could
  spend triage/remediation/checks, prove the finding no longer applied, and
  still end as `findings (no_changes_after_remediation)` with the stale review
  excerpt. That made the useful validation look like an unresolved failure.
- **Before / After:** before, every no-change remediation from a reused review
  was reported as unresolved findings, then briefly as an unknown resolved
  state. After, stale-review reuse has an explicit clear no-op resolved path,
  while compatible and explicitly supplied review files keep the existing
  no-change findings behavior unless they opt into the stale prompt path.
- **schema_version impact:** none. The stopped reason remains
  `stale_review_already_resolved`; the final status for that reason is now
  `clear` instead of `unknown`.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-06 — Git guard and commit-message side-effect hardening

- **Contract:** machine + human
- **What changed:** artifact dirty-path filtering now matches only exact path
  boundaries, so `artifacts2/...` and `artifacts-old/...` are no longer treated
  as children of `artifacts`. Successful commits refresh the expected `HEAD`
  even when RevRem runs from a repository subdirectory or linked-worktree-style
  checkout without a `.git` marker at `cwd`. Older pending-review prompts now
  display validation language. Commit-message drafting records and removes
  newly created non-artifact helper files, falls back to the deterministic
  subject, and aborts if the read-only phase modifies existing paths. If the
  commit-message harness commits the already-staged patch itself and leaves the
  repository clean, RevRem adopts that commit, records the side-effect artifact,
  and warns that the model/harness is unsuitable for future commit-message
  drafting; unsafe HEAD/index mutations still fail.
- **Why:** Dogfood with Gemini remediation showed two remaining auto-commit
  safety gaps, a confusing stale-review prompt, and an OpenCode commit-message
  draft that wrote `commit-subject.txt` despite the read-only contract.
- **Before / After:** before, sibling artifact-like paths could be ignored by
  dirty-worktree guards, subdirectory commits could leave `expected_head`
  stale, older-review prompts said "use", and a commit-message helper file
  could leak into the worktree. After, artifact exemptions are boundary exact,
  commit HEAD tracking works from supported cwd layouts, stale prompts say
  "validate", read-only commit-message helper files are diagnosed before
  committing, and clean self-commits are adopted with a prominent warning
  instead of turning into a misleading `git commit failed` error.
- **schema_version impact:** none. The side-effect diagnostic is an additive
  artifact and the summary gains an additive `commit_message_side_effects`
  collection.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-06 — Latest-review retry artifact and fragment trust hardening

- **Contract:** machine + human
- **What changed:** `--initial-review-file latest` now accepts only canonical
  generated review outputs (`review-N.txt` and `review-final.txt`) and ignores
  retry-attempt transcripts such as `review-1-attempt-1.txt`, even when
  `summary.json` lists them. Remediation prompt composition still fails hard
  for unresolved route/profile fragments, but unresolved
  triage-generated `required_fragments` are ignored and recorded as a visible
  warning in the remediation prompt.
- **Why:** Dogfood showed that `latest` could select provider retry output
  instead of review findings, and that a weaker triage model could invent a
  fragment name (`bounded-execution`) that aborted remediation before the
  finding was attempted.
- **Before / After:** before, a newer `review-*-attempt-*.txt` could seed a
  restart and any unresolved triage fragment could raise. After, retry
  transcripts are never usable latest-review candidates; model-invented
  fragments are advisory and dropped while trusted configured fragments remain
  strict.
- **schema_version impact:** none.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-06 — Provider timeout and secondary-prompt hardening

- **Contract:** machine + human
- **What changed:** `classify_provider_failure` now treats RevRem-enforced
  subprocess timeouts as non-transient when `returncode == -1` and the combined
  output contains `Command timed out after ...`, even if partial provider stdout
  precedes the timeout marker. The triage v2 prompt now gives exact
  `estimated_blast_radius` key names (`finding_count`, `module_count`) and
  minimal valid JSON examples. The commit-message prompt now explicitly asks for
  exactly one output line and includes good/bad examples to discourage
  explanatory prose.
- **Why:** Dogfood showed that local timeouts could be misclassified as
  retryable provider-transient failures when stdout came before stderr; it also
  showed secondary models using invalid triage key names and explaining commit
  subjects instead of outputting only the subject.
- **Before / After:** before, a local timeout with partial stdout could trigger
  provider retry logic; after, it is non-transient timeout evidence. Before,
  weaker triage/commit-message models had only prose instructions; after, they
  also receive concrete examples of valid and invalid output shapes.
- **schema_version impact:** none.
- **CHANGELOG:** Unreleased / Fixed and Changed.

### 2026-06-06 — Cleanliness check auto-stages remediation-created files

- **Contract:** machine + human
- **What changed:** The post-remediation cleanliness check no longer fails
  merely because remediation created a new non-artifact file. RevRem already
  refuses to enter `--commit-after-remediation` from a dirty worktree, including
  pre-existing untracked files. Given that clean-start invariant, `??` files
  that appear after remediation are treated as intentional remediation output
  and marked with `git add --intent-to-add`; the later commit phase's
  `git add -A` stages their contents. Files under `--artifact-dir` remain
  exempt.
- **Why:** Legitimate fixes often add tests, modules, or documentation. Blocking
  every post-remediation `??` path forced models to stage files during
  remediation or made valid fixes impossible. Known generated paths should be
  covered by `.gitignore` or `--artifact-dir`, while secrets and policy issues
  are the responsibility of configured verification/commit hooks.
- **Before / After:** before, a remediation that added `tests/test_new.py`
  failed the synthetic cleanliness check before `pytest`, `ruff`, or commit
  staging could run. After, the check runs `git add --intent-to-add --`
  for `tests/test_new.py`, records the auto-staged path in `check-N-1.txt`, and
  proceeds to the configured checks. If `git add --intent-to-add` fails, the
  check fails with the underlying git output.
- **schema_version impact:** none. Check artifact stdout can include an
  auto-staged path summary, but artifact names and summary structure are
  unchanged.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-06 — Cleanliness check auto-stages legitimate new files

- **Contract:** machine + human
- **What changed:** `run_worktree_cleanliness_check` now marks untracked
  non-artifact files with `git add --intent-to-add` instead of failing the
  check. The check still excludes files in the configured artifact directory,
  and any `git add -N` error surfaces the underlying git output. After the
  intent-to-add pass, the check re-runs `git status --porcelain`; if any
  untracked non-artifact files remain (e.g. the intent-to-add step ran but
  could not register a file), the check still fails with a list of the
  remaining paths. The successful summary now lists the auto-staged paths in
  `check-N-1.txt` for operator visibility.
- **Why:** Earlier revisions of the cleanup gate failed the loop before the
  commit phase could run `git add -A`, so any remediation that legitimately
  added a new file (a new test, module, or doc) had no way to pass checks
  without the model staging the file itself. Auto-staging with
  `--intent-to-add` is git-idiomatic: it registers the file with the index
  without writing content, so `git add -A` in the commit phase stages the
  full content normally, and the `??` flag that triggered the failure is
  removed.
- **Before / After:** before, a remediation patch that added
  `src/new_module.py` failed the worktree cleanliness check because the file
  showed as `?? src/new_module.py`. After, the cleanliness check runs
  `git add --intent-to-add -- src/new_module.py`, the re-check shows
  `A  src/new_module.py`, and the check records the auto-staged path in the
  artifact before passing. A `git add -N` failure (e.g. permission error)
  still fails the check with the underlying git error, so genuine scratch
  files that the operator must clean up by hand remain visible.
- **schema_version impact:** none. The check artifact gains an
  auto-staged-paths summary line, but its contract was previously
  "passes/fails with stdout body"; the additional line is purely additive
  and the surrounding event payload is unchanged.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-07 — CM2 preserves unknown review outcome on no-op remediation

- **Contract:** machine
- **What changed:** `core.engine._decide_commit` CM2 no longer collapses an
  `unknown` last review status into `OutcomeClear` when the commit phase
  reports `skipped_no_changes`. The branch now returns
  `Stop(OutcomeUnknown(reason="no_changes_after_remediation"))`, mapping to
  exit code 2, matching the prior behaviour and the post-loop `unknown`
  outcomes (F6, NF1). `clear` and `findings` mappings are unchanged. The
  unit test was renamed from
  `test_decide_cm2_unknown_skipped_no_changes_exits_clear` back to
  `..._exits_unknown` and its assertion updated; the
  `test_loop_stops_after_unknown_review_when_remediation_has_no_staged_changes`
  CLI commit integration test now expects `final_status: "unknown"`.
- **Why:** A bounded review-remediation loop that ends with an unknown
  review status has not received a clear review signal. Mapping that
  no-op commit back to `OutcomeClear` (exit code 0) marked an
  inconclusive review/remediation cycle as successful and broke operator
  intent for review harnesses that legitimately return `unknown` (e.g.
  harness timeouts or pre-loop stale review validation paths).
- **Before / After:** before, an unknown review followed by a no-op
  remediation exited 0 with `final_status: "clear"` and
  `stopped_reason: "no_changes_after_remediation"`; after, the same run
  exits 2 with `final_status: "unknown"` and the same
  `stopped_reason`. The 2026-06-03 entry below is superseded.
- **schema_version impact:** none; the JSON summary shape is unchanged
  (the `stopped_reason` value is unchanged; only the typed
  `final_status`/`OutcomeUnknown` mapping changes). The
  `stopped_reason` × `final_status` cross-reference table now lists
  `unknown` as a valid final status for `no_changes_after_remediation`.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-07 — Stale-resolved short-circuit and check-only cleanliness failure

- **Contract:** machine + human
- **What changed:** Two control-flow / check-semantics fixes in the
  post-remediation path:
  1. `core.engine._decide_checks` now short-circuits to
     `Stop(OutcomeClear(reason="stale_review_already_resolved"))` when
     `acc.stale_review_resolved` is True, before evaluating
     `_next_review_action`. The previous behaviour fell through to the
     next review action, which made `--no-final-review` runs end at
     `max_iterations_reached` and final-review runs issue a redundant
     provider call that masked the resolved state with a generic
     `review_clear`. The check is taken before commit and takes
     precedence over any pending check failures reported by the just-
     completed checks phase.
  2. `adapters.checks._cleanliness_check_untracked_no_commit` now
     returns `CommandResult(command, 1, ...)` when untracked non-artifact
     files remain in the worktree. The previous behaviour reported the
     untracked paths in the check stdout and returned exit code 0, which
     let the loop finish clear while leaving new files outside the
     reviewed `git diff` patch. The new output explicitly says
     `Worktree cleanliness check FAILED`, lists the untracked paths,
     and tells the operator to remove scratch files, stage legitimate
     files explicitly, or re-run with `--commit`.
- **Why:** Dogfood with stale-review validation showed that the
  no-commit resolved path could end with `max_iterations_reached`
  (because the checks branch returned to `_next_review_action` and the
  loop exhausted iterations before any `NoFinalReview` event was
  emitted), and that `--final-review` runs re-paid for a final review
  call after remediation had already proven the finding resolved.
  Separately, a non-auto-commit run that left an untracked helper file
  reported `check_failures: 0` while subsequent `git diff`-based
  review context silently omitted the file, allowing the loop to
  report clear with a new file outside the reviewed patch. Both gaps
  are correctness regressions introduced when the resolved/no-commit
  paths were wired in.
- **Before / After:** before, a stale-review-resolved run in
  `--no-final-review` mode returned `OutcomeUnknown(reason="max_iterations_reached")`,
  and the same run in final-review mode returned
  `OutcomeClear(reason="review_clear")` after a redundant review call.
  A non-auto-commit run that created an untracked helper file reported
  cleanliness as passed (exit 0). After, the resolved path returns
  `OutcomeClear(reason="stale_review_already_resolved")` without
  spending a final review call, and the cleanliness check fails with
  exit 1 and a list of the untracked paths. The
  `test_runner_shell_fails_if_stale_review_resolved_marker_commits_changes`
  acceptance test was rewritten as
  `test_runner_shell_skips_commit_when_stale_review_resolved` to
  document that the commit phase is no longer reached in this flow.
- **schema_version impact:** none. The stopped reason
  `stale_review_already_resolved` is unchanged; the change only
  re-routes the resolved state to an earlier short-circuit. The
  cleanliness check artifact gains a `FAILED` prefix in non-auto-commit
  mode; the surrounding event payload is unchanged.
- **CHANGELOG:** Unreleased / Fixed.

### 2026-06-05 — Bounded remediation-check inner retry and cleanup gate

- **Contract:** machine + human
- **What changed:** `ConfigSnapshot` now carries `inner_check_retries`, and
  `ChecksDone` with pending failures can produce a bounded
  `RetryViaChecks` action before the normal outer review loop continues. Retry
  artifacts use suffixed labels such as `remediation-1-retry-1.txt` and
  `check-1-retry-1-2.txt` while preserving the outer iteration number. Every
  checks phase now starts with a synthetic
  `git status --porcelain --untracked-files=all` cleanliness check whose
  result is written as `check-N-1.txt`; configured checks start at `.2`.
  `resume_config` and continue commands preserve `inner_check_retries`.
  Check progress renders captured RevRem timeout evidence as `timeout after
  Ns` instead of only showing negative signal return codes. If every failed
  check contains RevRem's own `Command timed out after ...` marker, the inner
  remediation retry is suppressed, the pending check failure remains, and a
  warning event records that the retry was skipped because the failure is a
  runtime budget issue rather than actionable code feedback.
- **Why:** Gemini and OpenCode dogfood showed that secondary remediation can
  repair review findings but leave check failures or scratch files behind.
  Feeding check output back to remediation once is cheaper and more targeted
  than forcing another full review pass, while the explicit cleanup check makes
  repository scratch files visible before commit staging.
- **Before / After:** before, remediation failure of `pytest`/`ruff` always
  advanced to the next review/final-review path. With
  `inner_check_retries = 1`, the first failed checks phase in an iteration
  emits a retry progress line and reruns remediation with the check output
  included; a second failed checks phase falls back to the existing outer loop.
  Before, a timeout artifact could display as `exit -1 (SIGHUP)`; now timeout
  marker text displays as `timeout after 300s`, and timeout-only check failures
  do not spend the configured inner remediation retry.
- **schema_version impact:** none. Summary/event fields are additive within
  existing runtime/check payloads, and artifact naming changes are recorded in
  `artifact_paths` as usual.
- **CHANGELOG:** Unreleased / Added and Changed.

### 2026-06-05 — Latest initial review compatibility guard

- **Contract:** machine + human
- **What changed:** `--initial-review-file latest` resolves candidates by
  run/review modification time and preserves the existing rule that a newer
  compatible clear run starts a fresh review instead of reviving older
  findings. When the current checkout's git state is available, historical run
  summaries without recorded git state are not treated as compatible latest
  candidates.
- **Why:** Dogfood showed that a stale carried-in review from an older codebase
  can trigger unnecessary triage/remediation and quota spend. A previous run
  that cannot prove it matches the current `HEAD`/base is safer to ignore than
  to remediate.
- **Before / After:** before, old runs without git-state metadata could be
  selected by `latest` and fed to remediation. After, `latest` starts fresh
  unless the newest unresolved candidate can prove git compatibility or the
  caller has no current git state to compare against.
- **schema_version impact:** none.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-05 — Gemini argv prompt delivery and timeout classification

- **Contract:** machine + human
- **What changed:** Gemini prompt-bearing phases now deliver bounded prompts
  with Gemini CLI's `--prompt` option and report
  `prompt_delivery == "argv-prompt"` in phase-start metadata. Phase-start
  `command` metadata redacts the prompt value as `<prompt chars=N>` while
  preserving command shape, prompt size, and prompt artifacts. RevRem refuses
  Gemini prompt delivery above the current `100000` byte CLI-delivery cap
  before launching the provider. Review subprocess stderr beginning with
  `Command timed out after ...` is classified as
  `provider_timeout` / non-transient, so `run_review_with_retry` does not spend
  a second full timeout retrying RevRem's own timeout kill.
- **Why:** Gemini dogfood showed direct `gemini --prompt` probes succeeded,
  but large stdin review invocations could run until the configured timeout
  with no provider output. The prior timeout path was also mislabeled as a
  transient provider interruption and retried once, doubling the wall-clock
  failure. The redaction keeps event metadata useful without duplicating large
  prompts into command arrays.
- **Before / After:** `gemini ... prompt=80.0k stdin truncated` becomes
  `gemini ... prompt=80.0k argv-prompt truncated`; timeout failures report
  provider timeout and fail after one configured deadline instead of retrying.
  Event `command` values store `--prompt <prompt chars=N>`, not the prompt
  body.
- **schema_version impact:** none; `prompt_delivery` values are additive within
  the existing phase-start payload schema, and command redaction preserves the
  existing field while reducing payload size.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-05 — Prompted review status-debug tightened

- **Contract:** machine + human
- **What changed:** review status diagnostics now report tool-denial evidence
  only when a provider-control stderr line itself begins with a denial marker.
  OpenCode shell transcripts written to stderr may contain reviewed diff lines
  or test fixtures mentioning `denied by policy`; those no longer set
  `tool_denial_present`. Prompted harness status-debug output also labels
  Codex-style finding bullets as `codex_bullets` and reports the explicit
  `REVIEW_STATUS` token, avoiding the misleading `findings=0` display.
- **Why:** OpenCode dogfood showed correct loop status interpretation but
  misleading diagnostics when stderr contained `git diff` output with denial
  fixture text. Explicit `REVIEW_STATUS` remains the loop-control authority.
- **Before / After:** `tool_denial_present=true` from a stderr diff transcript
  becomes `false`; a real provider-control denial includes
  `tool_denial_source="stderr_control"` and a short `tool_denial_evidence`
  string. `status-debug` for OpenCode/Gemini shows
  `explicit=findings codex_bullets=0` rather than `findings=0`.
- **schema_version impact:** none; diagnostic fields are additive and
  status-debug wording is human presentation.

### 2026-06-04 — Provider effort and denial diagnostics clarified

- **Contract:** machine + human
- **What changed:** phase config summaries now distinguish configured
  `reasoning_effort` from provider-enforced `provider_reasoning_effort`.
  Human summaries and TUI phase displays show `effort=n/a` for harnesses where
  RevRem cannot currently pass an effort control. Review diagnostics now set
  `tool_denial_present` only when the provider stderr/control section contains
  a denial marker, not when reviewed source or tests mention denial text.
- **Why:** dogfood runs with OpenCode/Gemini showed two misleading signals:
  non-Codex phases looked as if RevRem had set a thinking level, and denial
  fixtures in the reviewed diff could make a successful review look tool-blocked.
- **Before / After:** `phase_config.review.reasoning_effort = "low"` remains
  the configured intent; `phase_config.review.provider_reasoning_effort = null`
  and `reasoning_effort_supported = false` now describe provider reality for
  OpenCode/Gemini. Terminal/TUI output changes from `effort=low` to
  `effort=n/a` for those harnesses.
- **schema_version impact:** none; JSON fields are additive and existing
  configured-effort fields are preserved.

### 2026-06-03 — OpenCode file attachment requires a message

- **Contract:** machine
- **What changed:** OpenCode prompt-bearing commands now include the positional
  message `Follow the attached RevRem prompt exactly.` before
  `--file <prompt-artifact>`. Provider failure classification also treats
  OpenCode's `You must provide a message or a command` stderr as a CLI contract
  error.
- **Why:** live OpenCode review failed immediately because `opencode run --file
  <prompt>` attaches a file but does not provide a message. The installed CLI
  requires either positional `message` text or `--command`.
- **schema_version impact:** none; command argv and failure classification
  details are additive/behavioral within the existing v1 event envelope.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-03 — Gemini review context cap and quiet-run diagnostics

- **Contract:** machine
- **What changed:** the resolved runtime config briefly chose a larger
  Gemini Pro review-model cap when no CLI/profile cap was set; the later
  2026-06-05 Gemini argv prompt entry above supersedes that default and returns
  Gemini to the conservative prompted-review default. Review phase-start events add
  `review_context_chars`, `external_review_input_chars`, and
  `prompt_truncated`. Runtime summaries include
  `external_review_warning_seconds`, and external review waiting events add
  `quiet_warning` metadata after the configured non-terminating warning
  threshold.
- **Why:** Gemini dogfood showed the default `80k` character prompt cap could
  truncate a larger generated diff context, and long-running provider calls
  needed clearer diagnostics without changing `timeout=0` behavior.
- **schema_version impact:** none; additive runtime fields and event payload
  fields in the existing v1 envelopes.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-03 — Provider retry and commit-message subject fallback

- **Contract:** machine
- **What changed:** external review harnesses now classify common provider
  subprocess failures. Transient review failures emit a `review retry` progress
  event with `reason` and `attempt` metadata, write `review-N-attempt-1.txt`,
  and retry once before final failure. Non-transient provider failures surface
  provider-specific detail in the phase error without retrying. The
  commit-message phase now records `commit-N-message-fallback.json` with
  `reason: "model_drafting_invalid"` when a model returns explanatory prose
  instead of a subject, and it may consume `commit-N-message-subject.txt` as a
  subject sidecar when a harness extracts one.
- **Why:** OpenCode dogfood exposed provider server errors that should get one
  bounded retry, CLI-contract failures that should fail fast, and model
  commit-message prose that produced unusable committed subjects.
- **schema_version impact:** none; additive artifact/event details in the
  existing v1 envelopes.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-02 — Kilo prompt delivery switched from argv to stdin

- **Contract:** machine
- **What changed:** `prepare_prompt_invocation` no longer keeps kilo on a
  positional argv prompt path. Kilo now falls through to the same stdin branch
  Claude already uses. The phase-start event payload records
  `prompt_delivery == "stdin"` for kilo calls, and the saved remediation prompt
  is no longer embedded in argv when Kilo is selected. The deleted
  `test_prompt_invocation_passes_prompt_as_argument_for_argv_harnesses`
  coverage is superseded by
  `test_prompt_invocation_passes_prompt_via_stdin_for_kilo` and the
  parametrised `test_full_noninteractive_invocation_matches_real_cli_contract`
  (which asserts `expects_stdin=True` for Kilo).
- **Why:** Kilo's non-interactive CLI accepts the prompt from stdin in the same
  way Claude's does. Keeping a separate positional argv path for Kilo was
  duplicating the Codex-style behaviour that we no longer
  want for that harness, and it left Kilo with a contract that no hermetic test
  could verify. Gemini was initially moved along the same path, but the
  2026-06-05 Gemini dogfood entry above supersedes that part of the decision:
  Gemini now uses its documented `--prompt` option for bounded prompts because
  large stdin review invocations proved unreliable.
- **schema_version impact:** none; `prompt_delivery` is a new field on
  `phase_start` events introduced alongside the other prompt diagnostics in
  this release, and Kilo now populates it with `"stdin"` on first introduction
  (the argv positional prompt for this harness was an internal branch in
  `prepare_prompt_invocation` that is being removed at the same time, so no
  prior schema value is preserved).
- **CHANGELOG:** Unreleased / Added (Kilo stdin and Gemini `--prompt` delivery
  line supersedes the original combined wording).
- **Residual operator-side risk:** the kilo CLI's acceptance of prompts on
  stdin in non-interactive mode is only confirmed by the live smoke at
  `tests/test_live_secondary_harnesses.py::test_live_secondary_provider_direct_smoke`
  when `REVREM_LIVE_KILO=1`. Operators must run that live smoke at least
  once per kilo upgrade; if kilo ever changes its non-interactive contract
  to require a positional argument, every live kilo run will fail with
  empty input until the harness adapter is updated.

### 2026-06-02 — External harness progress and prompt diagnostics

- **Contract:** machine
- **What changed:** phase-start events now include the exact command argv,
  harness, prompt delivery mode, and prompt character/byte counts when a prompt
  is supplied. Resume summaries now include `external_review_input_chars`, and
  operator-cancellation diagnostics include the latest prompt/context artifact
  names and sizes when available. Human progress lines now render compact
  provider summaries such as `opencode run · model · n/a effort · timeout=0 ·
  sandbox read-only · prompt=80.0k file`. OpenCode prompt-bearing phases now
  attach the prompt artifact with `opencode run --file` instead of passing the
  prompt on stdin, and long-running model subprocesses emit additive `waiting`
  progress every five minutes.
- **Why:** OpenCode dogfood showed that long external-review calls could appear
  stuck with no visible evidence of prompt size, delivery mode, or exact phase
  invocation. The new fields make the saved artifacts useful for debugging
  provider hangs while keeping the terminal line readable.
- **schema_version impact:** none; additive fields within the existing v1 event
  and summary envelopes.
- **CHANGELOG:** Unreleased / Added.

### 2026-06-02 — Gemini dogfood progress and failure wording hardening

- **Contract:** human
- **What changed:** prompt-bearing phase-start commands now render a compact
  `<prompt chars=... first='...'>` summary instead of printing embedded prompt
  newlines into rich/compact progress. Unstructured review findings now show a
  first-line review summary before the `findings` status line. Remediation
  failures name the selected harness, for example `gemini remediation failed`,
  instead of the legacy `codex exec remediation failed` wording.
- **Why:** the first pure-Gemini dogfood run exposed confusing rich-panel
  wrapping, missing review-output context before triage/remediation, and a
  misleading provider label on Gemini remediation failure.
- **schema_version impact:** none.

### 2026-06-03 — CM2 unknown→clear mapping is also signalled by the test rename

- **Contract:** machine (test-name change is a leading indicator only)
- **What changed:** Nothing operational. The unit test that pins the
  commit-skip path's `final_status` was renamed from
  `test_decide_cm2_unknown_skipped_no_changes_exits_unknown` to
  `..._exits_clear` so a grep over test names reflects the new mapping.
- **Why:** `revrem.engine` CM2 now maps `skipped_no_changes` after an
  `unknown` review to `final_status: "clear"` (see the 2026-05-31 entry
  above). Renaming the test name is the cheapest way to make a future
  regression visible in the diff history without adding a new assertion.
- **schema_version impact:** none.
- **CHANGELOG:** Unreleased / Changed (CM2 row above already covers the
  behavioural change; this entry exists only to point at the test rename).
- **Superseded by:** 2026-06-07 entry above — the unknown→clear mapping was
  reverted; the renamed test is renamed back and the unknown case now exits
  unknown.

### 2026-05-31 — TASK-003 ledger closed

- **Contract:** none
- **What changed:** no runtime behavior changed. This entry records that
  `REVREM-TASK-003` is complete and the ledger is now the historical audit
  record for that task rather than an active work queue.
- **Why:** the task status was corrected to `Approved` with completion evidence
  on 2026-05-31. Future machine-contract changes should create new ledger
  entries under their owning task or plan rather than treating TASK-003 as open.
- **schema_version impact:** none.

### 2026-05-30 — Structured triage accepts review priority labels

- **Contract:** machine
- **What changed:** structured triage parsing now normalizes known review
  priority labels in finding severities before schema validation:
  `P0 -> critical`, `P1 -> high`, `P2 -> medium`, `P3 -> low`, and
  `P4 -> info`. Unknown severity values remain validation failures. Normalized
  payloads include a `parsing_warnings` entry documenting the repair.
- **Why:** the first live dogfood run produced a valid review finding with
  CodeRabbit-style `P2` severity in the triage JSON. Rejecting the entire
  payload prevented v2 routing artifacts even though the intended severity was
  unambiguous.
- **Before / After:** before, a v1/v2 triage payload with
  `"severity": "P2"` emitted `revrem.triage.invalid_output` and was discarded;
  after, it is accepted as `"severity": "medium"` and routing can proceed.
- **schema_version impact:** none; the stored artifact still conforms to the
  existing triage schemas after boundary normalization.
- **CHANGELOG:** not required; internal pre-release dogfood hardening.

### 2026-05-30 — Commit-message effort adjustment token corrected

- **Contract:** machine
- **What changed:** the operator-visible
  `phase_config.commit_message.reasoning_effort_adjustment` value for known
  Codex commit-message models changed from
  `codex_minimal_tool_incompatibility` to
  `codex_minimal_unsupported_by_model`.
- **Why:** live DF-001 testing showed `gpt-5.3-codex-spark` rejects
  `reasoning.effort=minimal` at the model-capability layer even after
  `web_search` is disabled, so the previous token misidentified the cause.
- **Before / After:** before, summaries and resume payloads attributed the
  adjustment to tool incompatibility; after, they attribute it to the known
  model capability gap.
- **schema_version impact:** none; pre-release `summary.json` remains at schema
  version `1.0` while correcting an enum-like detail value.
- **CHANGELOG:** not required; internal pre-release dogfood hardening.

### 2026-05-30 — Dogfood phase configuration details expanded

- **Contract:** machine
- **What changed:** `phase_config.commit_message` now records
  `requested_reasoning_effort` and `reasoning_effort_adjustment` alongside the
  effective `reasoning_effort`. `phase_config.triage` now records
  `routing_strict` and `allow_model_escalation` in the same summary projection
  used for resume-command reconstruction.
- **Why:** `REVREM-TASK-004` dogfood runs need to show when Codex commit-message
  `minimal` effort was promoted to `low`, and they need lossless triage/routing
  controls in profile-less resume output.
- **Before / After:** before, golden-master summary snapshots omitted these
  fields; after, the loop summary snapshots include null/default values for
  direct-config runs and populated values for CLI/profile-built dogfood runs.
- **schema_version impact:** none; pre-release `summary.json` remains at schema
  version `1.0` while adding optional detail fields.
- **CHANGELOG:** not required; internal pre-release dogfood hardening.

### 2026-05-29 — Phase configuration field provenance added to summaries

- **Contract:** machine
- **What changed:** each `phase_config` section in loop summaries and
  `resume_config.phase_config` now includes a `sources` object mapping
  individual fields to their source (`cli`, `profile:<name>`, `defaults`, or
  `direct-config`). The existing phase-level `source` field remains; phases
  with mixed field sources are marked `source == "mixed"`.
- **Why:** `REVREM-TASK-004` dogfood runs need auditable CLI-over-profile
  precedence without requiring operators to infer which field came from which
  layer.
- **Before / After:** before, summaries had only phase-level source markers;
  after, golden-master summary snapshots include empty `sources` objects for
  direct configurations and populated field maps for CLI/profile-built configs.
- **schema_version impact:** none; pre-release `summary.json` remains at schema
  version `1.0` while adding an optional object field.
- **CHANGELOG:** not required; internal pre-release dogfood hardening.

### 2026-05-29 — Dogfood phase configuration added to loop summaries

- **Contract:** machine
- **What changed:** loop `summary.json` now includes a `phase_config`
  projection covering review, triage, remediation, commit-message drafting, and
  checks. The projection records resolved harness/model/effort/timeout values,
  sandbox where relevant, and a source marker (`cli`, `profile:<name>`, or
  `defaults`) used for dogfood/debuggability. `resume_config` carries the same
  projection so resumed runs preserve explicit operator intent.
- **Why:** `REVREM-TASK-004` requires dogfood runs to be reproducible from
  artifacts without scraping terminal output or shell history.
- **Before / After:** before, summaries carried scattered resume/config fields
  but no compact phase plan; after, golden-master summary snapshots include
  `phase_config`.
- **schema_version impact:** none; pre-release `summary.json` remains at schema
  version `1.0` while adding an optional object field.
- **CHANGELOG:** not required; internal pre-release dogfood hardening.

### 2026-05-28 — Wave D SDK result exposes typed terminal outcome

- **Contract:** machine
- **What changed:** `application.run_review_loop()` and
  `application.resume_review_loop()` return `ReviewLoopResult`, carrying both
  the summary dict and the typed `RunOutcome` that produced final status and
  exit-code projections.
- **Why:** SDK callers must not branch on `summary["final_status"]` strings to
  understand terminal state; C5 requires typed outcomes at the boundary.
- **Before / After:** before, non-CLI callers received only summary-shaped data;
  after, callers inspect `ReviewLoopResult.outcome` and serialize with
  `to_dict()`.
- **schema_version impact:** none; persisted summary and artifact schemas are
  unchanged.
- **CHANGELOG:** not required; internal pre-release architecture task.

### 2026-05-28 — Setup failure summary contract pinned by headless API tests

- **Contract:** machine
- **What changed:** setup/preflight failures are codified as
  `final_status == "error"` with `stopped_reason == "setup_failed"` and
  `OutcomeFailed(reason="setup_failed")`.
- **Why:** Wave D headless tests make this exact pair an SDK-visible contract,
  so future changes must be intentional and ledgered.
- **Before / After:** behavior may have existed before Wave D; this entry
  records it as a governed contract from Wave D exit onward.
- **schema_version impact:** none.
- **CHANGELOG:** not required; internal pre-release architecture task.

### 2026-05-28 — Routing decision and outcome artifacts share one owner

- **Contract:** machine
- **What changed:** v2 routing writes both `routing-<n>.json` and
  `routing-outcome-<n>.json` through `routing_artifacts.py`. The outcome event
  payload records `exit_code`, rounded `wall_time_seconds`, and `checks_passed`
  for the remediation attempt associated with the routing decision.
- **Why:** the decision and outcome artifacts are a paired machine contract and
  should not drift across runner-shell and routing modules.
- **Before / After:** JSON/event shape is unchanged; ownership and acceptance
  coverage changed.
- **schema_version impact:** none.
- **CHANGELOG:** not required; internal pre-release architecture task.

### 2026-05-28 — CLI subcommand registry owns concrete command names

- **Contract:** human
- **What changed:** top-level CLI dispatch delegates concrete subcommand lookup
  to `cli/commands/registry.py`, including the intentional `ui -> tui.main`
  coupling. `cli/main.py` no longer owns concrete subcommand names.
- **Why:** Wave D demonstrates command extensibility by making the registry the
  single edit point for adding a command.
- **Before / After:** operator-visible commands and outputs are unchanged.
- **schema_version impact:** none.

### 2026-05-23 — B3c-iii: `_run_loop` wired through `decide()` + `_execute_stop()` (Wave B3c)

- **Contract:** human (stderr error messages only)
- **What changed:** all 11 `_run_loop` decision points now route through
  `decide(snap, acc, event)` and `_execute_stop(outcome, ...)`. State mutations
  (`state.set_final_status`, `state.set_stopped_reason`, `state.set_error`, etc.)
  are now executed exclusively inside `_execute_stop`. `main()` and
  `resume_main()` now call `outcome_to_exit_code(exc.outcome)` instead of
  pattern-matching on `exc.summary["stopped_reason"]`.

  **Human-presentation only change:** several failure cases that previously
  raised `RunLoopFailed` with a wrapped message (e.g.
  `"codex exec triage failed for iteration 1; see .revrem/triage-1.txt"`) now
  use the original exception string as the message. The `summary["error"]` field
  is unchanged (it was always `str(original_exc)`). Exit codes are unchanged.

- **Why:** extract the decision logic from the execution shell so that
  `decide()` is the sole authority over which outcome a branch produces, and
  `outcome_to_exit_code()` is the sole authority over exit codes. Eliminates
  the risk of `stopped_reason` string comparisons drifting out of sync with
  the outcome ADT.
- **Before / After:** machine contract (JSON summary, events.jsonl, exit codes)
  unchanged — golden masters still pass byte-for-byte.
- **schema_version impact:** none.

### 2026-05-23 — B3c-iv: `_run_loop` deletion deferred to C3 (Wave B3c)

- **Contract:** none (note only — no behaviour change)
- **What changed:** nothing. This entry records an intentional deferral.
  The B3c exit criterion in the task doc ("*Exit:* `_run_loop` deleted") is
  **not satisfied here** and is deferred to the C3 wave.
- **Why:** `_run_loop` cannot be deleted while `LoopConfig` still lives in
  `cli.py`. The `_config_snapshot()` helper that converts `LoopConfig` into a
  `ConfigSnapshot` is only possible as an inline shim. The full deletion
  requires C1 (command registry) to move `LoopConfig` out of `cli.py` first,
  at which point `_run_loop` collapses into a thin adapter wrapper and C3
  completes the facade deletion.
- **schema_version impact:** none.

### 2026-05-23 — B3a-prep: `_run_loop` branch → transition → outcome table (Wave B3a gate)

- **Contract:** none (documentation only — no production code changed)
- **What changed:** the complete enumeration of every decision branch, state
  mutation, and exit/raise in `_run_loop` (cli.py lines 1736–2424). This table
  is the mandatory B3a gate that must be committed before any engine-extraction
  code is written (plan note: "Branch→transition→outcome table committed to
  behaviour ledger BEFORE any engine code").
- **Why:** the state-machine extracted in B3b must be total over exactly these
  rows. Any branch not catalogued here will not be reachable from the pure
  `decide()` function, creating silent regressions invisible to golden-master tests.
- **schema_version impact:** none.

#### Reading guide

**"Outcome" column conventions:**
- `return summary` — function exits successfully, callers get the summary dict.
- `raise RunLoopFailed` — function exits with an error; callers distinguish via the raised exception.
- `raise` (bare) — exception propagates unchanged to an outer handler listed here.
- `continue` — current for-iteration body ends; loop advances to next iteration.
- *(implicit: loop continues)* — iteration body falls through to the next phase
  within the same iteration. Any row without one of the above exits falls into
  this category. See L-family rows below.

**"State mutation" column** lists only `state.set_*` calls (those that mutate
the `RunState`/summary dict). Writes to `iterations[-1]` fields are noted inline
where they differ from what `state.set_*` captures.

#### Inputs to `decide()` (B3b pre-requisite)

A pure `decide()` function must receive every value that gates a branch. The
complete set, drawn from the left-column conditions above, is:

| Input | Type | Source |
|---|---|---|
| `iteration` | `int` | loop counter |
| `status` | `Literal["clear","findings","unknown"]` | last review result |
| `pending_check_failures` | `str` (empty = none) | accumulated check output |
| `_commit_retry` | `bool` | set True on CM3 |
| `triage_no_actionable` | `bool` | triage outcome |
| `suppressed_count` | `int` | triage outcome |
| `triage_payload` | `dict \| None` | triage outcome |
| `resolved_route` | `ResolvedRoute \| None` | routing outcome |
| `commit_status` | `str \| None` | commit outcome (`skipped_no_changes`, etc.) |
| `commit_exc` | `CommitFailed \| None` | commit failure details |
| `review_exc` | `RuntimeError \| None` | review failure |
| `triage_exc` | `Exception \| None` | triage failure |
| `remediation_exc` | `Exception \| None` | remediation failure |
| `commit_other_exc` | `Exception \| None` | commit non-CommitFailed failure |
| `config.max_iterations` | `int` | config |
| `config.commit_after_remediation` | `bool` | config |
| `config.commit_on_hook_failure` | `str` | config |
| `config.triage_enabled` | `bool` | config |
| `config.final_review` | `bool` | config |

Config fields are read-only and can be passed as a bundle. The phase-result
fields (`review_exc`, `triage_exc`, etc.) represent "what happened this phase"
and are None when the phase succeeded. B3b should wrap these into a typed
`PhaseResult` value object per phase so `decide()` pattern-matches on an ADT
rather than an open dict.

#### Action ADT (B3b design note)

`decide()` returns one of these Actions (compound mutations — never three
separate setter calls):

| Action | State fields set | Side-effect (shell, not decide) |
|---|---|---|
| `Continue` | — | loop advances |
| `RetryViaCommitHook(hook_output)` | `pending_check_failures=True` | `continue` next iteration |
| `ExitClear(reason, excerpt)` | `final_status=clear`, `stopped_reason=reason`, `latest_review_excerpt=excerpt` | `return summary` |
| `ExitFailed(reason, error, *, staged=False, checks=False)` | `final_status=error`, `stopped_reason=reason`, `error=error`, optionally `staged_changes_left`, `pending_check_failures` | `raise RunLoopFailed` |
| `ExitFindings(reason)` | `final_status=findings`, `stopped_reason=reason`, optionally `pending_check_failures=True` | `return summary` |
| `ExitUnknown(reason)` | `final_status=unknown`, `stopped_reason=reason`, `pending_check_failures=bool(pending)` | `return summary` |
| ~~`ExitLastStatus(reason)`~~ | ~~removed~~ | CM2 passes `last_review_status` in `LoopAccumulator` so `decide()` returns `ExitClear`/`ExitFindings`/`ExitUnknown` concretely — no shell-side lookup. `ExitWithLastStatus` was removed as dead code after B3b. |

The A2/A2b golden-master snapshots (not this table) are the verification
contract: B3b must leave those byte-identical.

#### Current engine ADT coverage (Wave C closeout)

The implementation now represents exits through `Stop(RunOutcome)` rather than
separate `Exit*` action variants. This table pins each current `PhaseEvent` and
`Action` variant to the branch rows below so future engine refactors cannot add
an unledgered transition.

| Engine type | Ledger row(s) | Meaning |
|---|---|---|
| `LoopStarted` | R1, R2 | Begin an iteration by requesting `RunReview(is_final=False)`. |
| `ReviewDone` | R3, E1, F2-F6 | Review result gates review failure, early clear, triage/remediation, or final outcomes. |
| `TriageDone` | T2-T6 | Triage either exits clear/failed or requests remediation. |
| `RemediationDone` | M2-M3, CK1 | Remediation failure exits; success requests checks. |
| `ChecksDone` | CK1, L1-L2, CM1 | Checks update pending failures, then either request commit or advance review. |
| `CommitDone` | CM1-CM7, L3-L4 | Commit status either exits, retries via hook output, or advances review. |
| `NoFinalReview` | NF1 | Exhausted loop without final review exits unknown. |
| `Continue` | L1-L4 | Advance to the next iteration. |
| `RunReview` | R1, R2, F1 | Execute iteration or final review. |
| `RunTriage` | T1 | Execute triage for review findings. |
| `RunRemediation` | M1 | Execute remediation. |
| `RunChecks` | CK1 | Execute verification checks after remediation. |
| `RunCommit` | CM1-CM7 | Execute optional commit when checks are clear. |
| `RetryViaCommitHook` | CM3, L4 | Feed retryable commit hook output into the next remediation iteration. |
| `Stop` | P1, R3, E1, T2-T3, T6, M3, CM2, CM4-CM5, CM7, F2-F6, NF1, X1-X2 | Terminal outcome wrapper applied by the shell. |

#### `_run_loop` pre-loop guards (before state is initialised)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| G1 | `config.max_iterations < 1` | — | `raise ValueError` (no summary written) |
| G2 | `commit_after_remediation and not dry_run` and `git worktree status` returncode ≠ 0 | — | `raise RuntimeError` (no summary written) |
| G3 | `commit_after_remediation and not dry_run` and worktree has dirty lines | — | `raise RuntimeError` (no summary written) |

#### Pre-loop after state initialised (preflight block)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| P1 | `preflight_enabled and not dry_run` and `diagnostics.has_blocking_issue(issues)` | `final_status=error`, `stopped_reason=setup_failed`, `error="preflight diagnostics found blocking issue"` | `raise RunLoopFailed` (summary written, `diagnostics.json` written) |

#### Initial-review bootstrap (before iteration 1)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| I1 | `config.initial_review_file` is set | (no state mutation; writes `review-initial.txt`, emits `progress` event) | loop continues with `initial_review_output` pre-loaded |

#### Per-iteration — review phase

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| R1 | `iteration == 1 and initial_review_output` | appends `{iteration, review_status, review_source}` to `iterations` | skips review subprocess; uses loaded output |
| R2 | otherwise (normal review run) | appends `{iteration, review_status}` to `iterations` | review subprocess (via harness or legacy shim) |
| R3 | `RuntimeError` raised during review | `final_status=error`, `stopped_reason=review_failed`, `error=str(exc)` | `raise RunLoopFailed` (summary written) |

#### Per-iteration — early-exit after review

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| E1 | `status == "clear" and not pending_check_failures` | `final_status=clear`, `stopped_reason=review_clear`, `latest_review_excerpt=…` | `return summary` |

#### Per-iteration — triage phase (only when `config.triage_enabled`)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| T1 | `triage_enabled` — triage runs (harness or legacy shim) | appends `suppressed_findings_count` to `iterations[-1]` when > 0 | sets `remediation_input` / `suppressed_count` / `triage_no_actionable` / `triage_payload` |
| T2 | `triage_no_actionable and suppressed_count and not pending_check_failures` | `final_status=clear`, `stopped_reason=all_findings_suppressed`, `suppressed_findings_count=suppressed_count`, `latest_review_excerpt=…` | `return summary` |
| T3 | `triage_no_actionable and not suppressed_count and not pending_check_failures` | `final_status=clear`, `stopped_reason=triage_rejected_all_findings`, `latest_review_excerpt=…` | `return summary` |
| T4 | `triage_no_actionable and pending_check_failures` | — (no state change; `remediation_input` set to `pending_check_failures`) | loop continues into remediation |
| T5 | `BudgetExceeded` during triage | — | re-raised (caught by outer `BudgetExceeded` handler) |
| T6 | any other exception during triage | `final_status=error`, `stopped_reason=triage_failed`, `error=str(exc)`, `iterations[-1]["triage_failed"]=True` | `raise RunLoopFailed` (summary written) |

#### Per-iteration — routing (inside triage block, only when `triage_payload and triage_contract=="v2" and profile_v2 and routing.enabled`)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| RT1 | routing enabled — `resolve_routing` succeeds | emits `routing_decision` event, writes `routing-N.json` + `remediation-N-prompt.txt` | `resolved_route` set; loop continues |
| RT2 | `TriageValidationError` from `validate_routing_payload` | (none on `state`; writes `diagnostics-N.json`; emits `triage.invalid` progress event) | `raise RuntimeError` → caught by T6 handler → `raise RunLoopFailed` |

#### Per-iteration — remediation phase

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| M1 | remediation runs successfully (harness or legacy shim) | `rem_result`, `rem_duration` captured; `routing_outcome` event emitted when `resolved_route` set | loop continues |
| M2 | `BudgetExceeded` during remediation | — | re-raised |
| M3 | any other exception during remediation | `final_status=error`, `stopped_reason=remediation_failed`, `error=str(exc)`, `iterations[-1]["remediation_failed"]=True` | `raise RunLoopFailed` (summary written) |

#### Per-iteration — checks (always runs after remediation)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| CK1 | checks run (harness or legacy shim) | `state.set_pending_check_failures(bool(pending_check_failures))`, `iterations[-1]["check_failures"]=len(failed_check_names)` | `pending_check_failures` and `failed_check_names` updated |

#### Per-iteration — commit phase (only when `commit_after_remediation and not pending_check_failures`)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| CM1 | commit succeeds | `iterations[-1]["commit_status"]=status` | loop continues (or returns on `skipped_no_changes`) |
| CM2 | `commit_status == "skipped_no_changes"` | `final_status=clear` when last review status is `clear`; `final_status=unknown` when the last review was indeterminate; `final_status=findings` only when the last review explicitly found findings. `stopped_reason=no_changes_after_remediation`, `latest_review_excerpt=…` | `return summary` |
| CM3 | `CommitFailed(kind="hook_failed")` and `commit_on_hook_failure in {remediate, no-verify}` and `iteration < max_iterations` | `iterations[-1]["commit_status"]=hook_failed`, `_commit_retry=True`, `pending_check_failures=hook output`, `state.set_pending_check_failures(True)` | `continue` (next iteration, retrying with hook output as remediation input) |
| CM4 | `CommitFailed(kind="hook_failed")` (non-retryable) | `final_status=error`, `stopped_reason=commit_hook_failed`, `error=str(exc)`, `staged_changes_left=True`, `pending_check_failures=True` | `raise RunLoopFailed` (summary written) |
| CM5 | `CommitFailed` other kind | `final_status=error`, `stopped_reason=commit_failed`, `error=str(exc)` | `raise RunLoopFailed` (summary written) |
| CM6 | `BudgetExceeded` during commit | — | re-raised |
| CM7 | any other exception during commit | `final_status=error`, `stopped_reason=commit_failed`, `error=str(exc)`, `iterations[-1]["commit_failed"]=True` | `raise RunLoopFailed` (summary written) |

#### Per-iteration — normal continuation (loop continues to next iteration)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| L1 | `status != "clear"` and triage not short-circuiting and remediation + checks succeed and `not commit_after_remediation` | `pending_check_failures` updated from check results | *(implicit: loop continues)* |
| L2 | `status != "clear"` and triage not short-circuiting and remediation + checks succeed and `commit_after_remediation and pending_check_failures` (commit skipped due to failures) | `pending_check_failures` updated | *(implicit: loop continues)* |
| L3 | commit succeeds (CM1) and `commit_status != "skipped_no_changes"` | `iterations[-1]["commit_status"]=status` | *(implicit: loop continues)* |
| L4 | CM3 hook-failure retry — `_commit_retry=True` set | `pending_check_failures=True` set | `continue` (begins next iteration with hook output as remediation input) |

#### Post-loop — final review (when `config.final_review`, entered after all iterations exhausted)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| F1 | final review runs successfully | `latest_review_excerpt=…` | sets `status` and `final_review` for subsequent branches |
| F2 | `RuntimeError` from final review | `final_status=error`, `stopped_reason=review_failed`, `error=str(exc)`, `iterations.append({iteration:"final", review_failed:True})` | `raise RunLoopFailed` (summary written) |
| F3 | `pending_check_failures` after final review | `final_status=findings`, `pending_check_failures=True`, `stopped_reason=max_iterations_reached_with_check_failures` | `return summary` |
| F4 | `status == "clear"` after final review (no pending check failures) | `final_status=clear`, `stopped_reason=review_clear` | `return summary` |
| F5 | `status == "findings"` after final review | `final_status=findings`, `stopped_reason=max_iterations_reached` | `return summary` |
| F6 | `status == "unknown"` after final review | `final_status=unknown`, `stopped_reason=max_iterations_reached`, appends `{iteration:"final", review_status:"unknown"}` | `return summary` |

#### Post-loop — no final review (`not config.final_review`)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| NF1 | all iterations exhausted, no final review | `final_status=unknown`, `pending_check_failures=bool(pending_check_failures)`, `stopped_reason=max_iterations_reached` | `return summary` |

#### Outer exception handlers (wrap entire try block)

| # | Branch condition | State mutation | Outcome |
|---|---|---|---|
| X1 | `KeyboardInterrupt` | `final_status=error`, `stopped_reason=cancelled`, `error="cancelled by operator"` | `raise RunLoopFailed` (writes `diagnostics.json`, emits `cancellation` event, summary written) |
| X2 | `budgets.BudgetExceeded` | `final_status=error`, `stopped_reason=budget_ceiling_hit`, `error=str(exc)` | `raise RunLoopFailed` (summary written) |

#### `stopped_reason` × `final_status` cross-reference

| `stopped_reason` | `final_status` | Row(s) |
|---|---|---|
| `setup_failed` | `error` | P1 |
| `review_failed` | `error` | R3, F2 |
| `review_clear` | `clear` | E1, F4 |
| `triage_rejected_all_findings` | `clear` | T3 |
| `all_findings_suppressed` | `clear` | T2 |
| `triage_failed` | `error` | T6 |
| `remediation_failed` | `error` | M3 |
| `no_changes_after_remediation` | `clear` \| `findings` \| `unknown` | CM2 |
| `commit_hook_failed` | `error` | CM4 |
| `commit_failed` | `error` | CM5, CM7 |
| `max_iterations_reached_with_check_failures` | `findings` | F3 |
| `max_iterations_reached` | `clear` \| `findings` \| `unknown` | F4–F6, NF1 |
| `cancelled` | `error` | X1 |
| `budget_ceiling_hit` | `error` | X2 |

### 2026-05-22 — B0a structural spine: ports.py + RunContext (Wave B0a)

- **Contract:** machine (no behaviour change — structural)
- **What changed:** nothing observable. Added `core/ports.py` as the canonical
  port import surface: **moved `CommandResult` here** (out of `cli.py`, which now
  re-exports it), defined the `ProcessRunner` Protocol, and defined `RunContext`
  (a frozen bundle of collaborators: `clock`, `identity`, `runner`, `event_sink`,
  `budget_state`). `Clock`/`RunIdentity`/`EventSink` are **re-exported** from
  their current homes, not moved. Promoted the import-linter config with a partial
  C4 contract (`core.*` must not import `cli` or `argparse`;
  `include_external_packages=true`).
- **Plan divergences resolved (amended in this commit):**
  1. **B0 split into B0a/B0b** (this is B0a) — structural spine vs. the risky
     collaborator relocation.
  2. **`RunContext` carries collaborators only, not config.** C7's literal
     "config + ports" collides with C4: `LoopConfig` is an edge type (`cli.py`,
     imports `profiles`) so a core-homed `RunContext` cannot hold it. Glossary +
     C7 softened; config folds onto `RunContext` once `LoopConfig` is core-homed
     post-B1. Phases will take `config` + `ctx` separately in B0b.
  3. **`Harness`/`ProgressReporter`/`ArtifactStore`/`GitGateway` deferred** to
     B2/B4 (no consumer today — avoids the "hexagonal cosplay" Non-Goal).
  4. **Clock/RunIdentity/EventSink re-exported, not physically re-homed.**
     Physically moving `Clock` into the core while `events` still imports it
     would create an import cycle (`ports → events → clock → ports`). The
     dependency *inversion* is deferred to B2 when the layered contract and the
     `adapters/` package land. The partial forbidden-list contract is honest to
     what exists today rather than near-empty `layered` theatre.
- **Why move `CommandResult`:** the `ProcessRunner` port returns it, and the core
  cannot import `cli` (C4) — so the value type had to come into the core. The
  plan's Open Question ("home for `CommandResult`") is resolved: `core/ports.py`.
- **Tests:** `tests/test_ports.py` pins the surface (CommandResult homed +
  cli re-export identity, the declared protocols present, the deferred ports
  absent, RunContext bundles collaborators with no `config` field).
- **schema_version impact:** none.

### 2026-05-22 — A3 RunState behind the summary dict (Wave A3)

- **Contract:** machine (no behaviour change — shadow refactor)
- **What changed:** nothing observable. Added `core/state.py` with the typed
  `RunState` aggregate and wired it into `_run_loop`. The initial `summary`
  literal is now `RunState.create(...)`; the 33 in-loop scalar terminal writes
  (`final_status`, `stopped_reason`, `error`, `latest_review_excerpt`,
  `suppressed_findings_count`, `pending_check_failures`, `staged_changes_left`)
  go through low-level transition methods (`state.set_*`).
- **Approach (as-built — "(b1)"):** `RunState` holds the **live** summary dict
  and iterations list — the same objects the loop still reads — so the ~46
  `summary[...]` reads and 17 `iterations` mutations are untouched. `to_dict()`
  returns that live dict, which `write_summary` augments (contract / artifact
  paths / budgets) at emit time exactly as before.
- **What "byte-for-byte" maps to here:** because `to_dict()` returns the same
  object the loop reads, an in-process `state.to_dict() == summary` assertion
  would be vacuous, so it is **not** added. The real equivalence gate is the **A2
  golden masters staying byte-identical** (clear / findings / budget / cancel),
  backed by the existing `tests/test_cli.py` coverage of the branches A2 does not
  snapshot (commit/hook-retry, no-changes, suppressed/triage-rejected,
  setup/commit/review failures, max-iter-with-check-failures). Full suite green
  (558 passed) with zero snapshot diffs.
- **Scope held (intentional non-change):** the 4 `object.__setattr__(config, …)`
  calls (`event_sink`, `budget_state`) are **left in place** — they are
  collaborators, not run-state, and their removal is owned by B0/C7. The
  write-time augmentation helpers (`add_summary_contract_fields`,
  `add_artifact_paths`, `update_unexpected_behaviors`, `summary_budget_payload`)
  are reporting layer and were not touched.
- **Naming:** transitions are deliberately low-level (one setter per write site);
  semantic transitions (`mark_clear`, `mark_failed(reason)`) and the `RunOutcome`
  ADT are layered on in B3 once the branch→outcome survey exists.
- **Dependency rule:** `core.state` added to the import-linter source list — it
  imports stdlib only (C4).
- **Tests:** `tests/test_run_state.py` pins `RunState`'s own API in isolation
  (create shape, `commit_no_verify` derivation, live-dict / shared-list identity,
  setters) — a *separate* concern from the A2 byte-for-byte gate, not a
  substitute for it. (Note for B3a, which touches `RunState` next.)
- **schema_version impact:** none.

### 2026-05-22 — A2b loop-path golden masters (Wave A2b)

- **Contract:** machine (additional baseline captures, no behaviour change)
- **What changed:** nothing in production code. Pinned the three remaining
  **loop terminations** using the A2a machinery:
  `loop_findings_summary.json` / `loop_findings_events.json`
  (findings remain, iterations exhausted — `stopped_reason=max_iterations_reached`,
  `final_status=unknown`), `loop_budget_summary.json` / `loop_budget_events.json`
  (token-budget ceiling — `stopped_reason=budget_ceiling_hit`,
  `error="tokens budget reached: 100 >= 10"`, with `cost_charge`/`cost_ceiling_hit`
  events), and `loop_cancel_summary.json` / `loop_cancel_events.json`
  (operator `KeyboardInterrupt` — `stopped_reason=cancelled`,
  `error="cancelled by operator"`, `diagnostics.json` + `cancellation` event).
- **Test-support change (not production):** `tests/support/fakes.py` `FakeRunner`
  now raises a mapped value when it is a `BaseException` (returns it otherwise),
  so the cancel path is drivable through `run_loop(config, runner, …)`.
- **Why:** complete the loop half of the C3 change-detector so B2/B3 cannot
  silently alter the failure/exhaustion machine contract.
- **Before / After:** baseline; these snapshots are now authoritative alongside
  the A2a clear-path pair.
- **Normalizer scope:** unchanged from A2a (run-dir paths → `<RUN_DIR>`,
  `wall_elapsed_seconds` → `<DURATION>`). No git-SHA / byte-size placeholders
  were needed — the loop fixture runs in a non-git tmp dir (`git_state.available`
  = false, all SHAs null) and no path emits a byte size. Those placeholders
  remain deferred to A2c with their first real consumer.
- **Scope note:** per-subcommand snapshots were **split out of A2b into a new
  A2c** (plan amended in this commit). Rationale: a subcommand's result is its
  own `CommandOutcome` ADT (C5), a different output shape from the loop's
  `RunOutcome`; pinning them belongs after C1/C5 stabilise those types.
- **schema_version impact:** none.

### 2026-05-21 — A2a golden-master baseline (Wave A2a)

- **Contract:** machine (baseline capture, no behaviour change)
- **What changed:** nothing in production code. Added the golden-master
  machinery (`tests/support/{fakes,normalize,snapshot}.py`, `tests/conftest.py`)
  and committed the first pinned machine-contract snapshots for the loop
  **review-clear** path: `tests/snapshots/loop_clear_summary.json` and
  `loop_clear_events.json`.
- **Why:** establish the change-detector (C3) so later waves cannot silently
  alter the machine contract.
- **Before / After:** baseline; these snapshots are now authoritative. Any
  future diff is either a ledgered intentional change (regenerate with
  `REVREM_UPDATE_SNAPSHOTS=1`) or a CI failure.
- **Normalizer scope:** run-dir paths → `<RUN_DIR>`, `wall_elapsed_seconds` →
  `<DURATION>` (the budget wall-time carve-out from the A1 entry). git-SHA and
  byte-size placeholders are deferred to A2b (null / stable on this path).
- **schema_version impact:** none.

### 2026-05-21 — A1 Clock + RunIdentity seam (Wave A1)

- **Contract:** machine
- **What changed:** nothing observable. The loop now reads wall/monotonic time
  via an injected `Clock` and run-scoped ids via an injected `RunIdentity`
  (`clock.py`, `identity.py`), threaded as keyword args through `run_loop` /
  `_run_loop` / `write_summary` / `add_summary_contract_fields` /
  `default_artifact_dir`, and `events.JsonlSink` stamps `Event.ts` from its
  injected clock. **Defaults are the real clock / real `uuid4`, so production
  output is byte-for-byte identical.** Determinism only appears when a fake is
  injected (tests).
- **Why:** remove the #1 nondeterminism source so the A2 golden-master suite
  can pin the machine contract (C6).
- **Before / After:** identical for real runs; `tests/test_clock_identity_seam.py`
  demonstrates that a fake clock/identity makes `run_id`, `started_at`,
  `finished_at`, every `events.jsonl` `ts`, and the default artifact-dir suffix
  deterministic.
- **schema_version impact:** none.
- **Carve-out recorded for A2:** budget wall-time fields
  (`summary["wall_elapsed_seconds"]` and the `budgets` elapsed) are **not**
  injected in A1 — they stay on the real monotonic clock and must be
  **normalized by the A2 comparator**. Rationale: injecting them would require
  threading a clock through the budget read helpers, expanding A1's blast
  radius for no machine-contract benefit (the fields are measured durations
  that snapshots normalize regardless). The real-time-sensitive sites
  (double-Ctrl-C debounce, subprocess timeout deadlines) and human-display
  timestamps stay real by design, annotated `# det-exempt:` and enforced by
  `tests/test_determinism_gate.py`.
