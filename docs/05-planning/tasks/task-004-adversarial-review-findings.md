---
document_id: REVREM-REVIEW-004
type: TASK
title: Adversarial review findings for TASK-004 dogfood hardening
status: Draft
version: '1.2'
last_updated: '2026-05-29'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Adversarial re-evaluation of the Codex-declared completion of
  REVREM-TASK-004, with reproducible test-integrity findings and required
  remediations to hand back to Codex.
keywords:
- revrem
- dogfood
- adversarial-review
- test-hermeticity
- remediation
related_ids:
- REVREM-TASK-004
- REVREM-TASK-003
---


# TASK-004 — Adversarial Review Findings

> **This document has two rounds.** Round 2 (below) is the current,
> authoritative re-evaluation after Codex's second completion claim. Round 1 (at
> the bottom) is retained for history; **all Round 1 blockers and mediums are
> remediated** and re-verified in Round 2.

> **Codex remediation status (2026-05-29):** Round 2 findings R2-1 through
> R2-7 have been remediated in the follow-up implementation pass. The closeout
> evidence is recorded in `REVREM-TASK-004`; the historical findings below are
> retained as the review record that drove the changes.

---

## Round 2 — re-evaluation after hermeticity remediation (2026-05-29)

- **Reviewer:** Claude (Opus 4.8), adversarial re-evaluation against the 6 axes.
- **Verdict:** **Close, but NOT yet complete.** The Round 1 blockers are
  genuinely fixed: `pytest -q` (833 tests) is now green in **both** `/tmp`
  states, and `ruff`, `mypy`, `lint-imports`, and `meminit check` all pass. The
  feature work is strong and largely demonstration-class. It cannot be marked
  done because **slice T4d is only half-built**: the DF-004 requirement that
  executable route chains be validatable "when routing is enabled **or** a
  lint/doctor command explicitly asks for executable-route validation" has no
  on-demand path, and T4d's required "fails-when-requested" test was never
  added (R2-1). Three further acceptance/documentation gaps (R2-2/3/4) and three
  quality polish items (R2-5/6/7) remain.
- **Method:** Read the committed source for the T4a–T4f slices and every named
  DF item; ran the full gate (`ruff`, `mypy`, `lint-imports`, `meminit check`,
  `pytest -q`) in clean and `/tmp/.git`-polluted states; ran live dry-run
  Matrices D and F end-to-end; verified `--disable web_search` is a real
  `codex exec 0.135.0` flag; traced each finding to a specific source line.
  Note on DF-001: the "`--commit-reasoning-effort minimal` succeeds" criterion
  is verified here by command-shape assertion (the scoped `--disable web_search`
  is present and is a real flag), not by a live commit-message model call —
  adequate for a code review, but the evidence basis is command shape, not a
  round-trip against Codex.

### Round 2 scorecard

| Axis | Verdict | Basis |
|---|---|---|
| 1. Complete | **No** | T4d on-demand executable-route validation unbuilt; its required "fails-when-requested" test is missing (R2-1). |
| 2. Highest quality | **Mostly yes** | Clean, well-targeted slices; three minor polish items (dead `unbounded_when_none` param, call-for-side-effect remnant, gated `default_route` check) — R2-5/6/7. |
| 3. Modular / hexagonal | **Yes** | `lint-imports` 9/9 kept. Round 1 port leak fixed: `git_repo_root` now goes through the injected runner and degrades to `None`. |
| 4. Properly tested | **Mostly yes** | Suite hermetic in both `/tmp` states (833 passed). Gap: T4d's "fails-when-requested" executable-validation test is absent because the opt-in mode is unbuilt (R2-1). |
| 5. Documented (Meminit DocOps) | **Partial** | `meminit check` green; dogfood profile + phase_config well documented. New triage/routing CLI flags absent from DEVEX-001; `--commit-message-harness` omission undocumented (R2-2/4). |
| 6. Demonstration-class | **Nearly** | The hermeticity fix, web_search scoping, explicit-`0` projection, and field-level provenance are genuinely star-senior. Shipping a test that locks in a spec violation is the one thing holding it back. |

### Round 1 closure (re-verified, all remediated)

| Round 1 finding | Status | Evidence |
|---|---|---|
| B1 — non-hermetic commit tests / dead call hard-raise / port leak | **Fixed** | `git_repo_root` uses injected runner + returns `None` (`commit.py:39-49`); `test_no_staged_changes_without_repo_root_returns_skipped_no_changes` added; suite green clean. |
| B2 — incomplete temp-root exclusion / duplicated walkers | **Fixed** | Centralized in `repo_roots.py`; `temp_root_candidates()` excludes the temp root **and all parents**; suite green with `/tmp/.git` present. |
| M3 — stray mis-formatted review artifact | **Fixed** | `docs/tasks/TASK-004-adversarial-review.md` deleted; `meminit check` → `success:true` (29 files). |
| M4 — incomplete resume command | **Fixed** | `_resume_command` now emits base, max-iterations, profile/checks, timeout, commit mode, hook policy, initial-review-file (`runtime.py`). |
| M5 — fallback ignored review context | **Fixed** | `_commit_type(..., context=)` infers feat/refactor/perf from review/remediation context (`commit.py:324-336`). |
| M6 — coarse phase source markers | **Fixed** | Field-level `phase_config.*.sources` + phase-level `source` with explicit `mixed` (`config_builder.py`); confirmed live in Matrix D JSON. |

---

## Round 2 findings (hand back to Codex)

### R2-1 — (HIGH / blocks "complete") T4d on-demand executable-route validation is unbuilt, and a test codifies the violation

DF-004 and slice T4d require two independent triggers for executable
route-chain validation: **(a)** routing enabled, **or** **(b)** "a lint/doctor
command explicitly asks for executable-route validation." Only trigger (a) was
built.

- `profiles.validate_policy` (the `revrem policy lint` path) **early-returns
  `[]` when routing is disabled** (`profiles.py:1045-1046`), so `policy lint`
  can never surface a draft route's missing/unimplemented harness chain.
- `runner_setup.profile_routed_harnesses` and the doctor copy
  (`cli/commands/doctor.py:79-82`) both **early-return `()` when routing is
  disabled**, so `revrem doctor` skips route-harness executable checks entirely.
- There is **no flag** on `policy` or `doctor` (`cli/args.py`) to *request*
  executable-route validation — trigger (b) simply does not exist.
- The committed `tests/test_cli_doctor_integration.py::
  test_doctor_profile_skips_unused_route_harnesses_when_routing_disabled` is
  **correct** — it exercises the *default* path (nobody opted in, routing
  disabled), where DF-004 mandates skipping. The gap is the opposite: T4d's
  explicitly-required test — "the same profile **fails** `policy lint` or doctor
  executable validation **when requested**" — is **absent**, because the opt-in
  mode it would exercise was never built.

**Required fix:**
1. Add an opt-in mode, e.g. `revrem policy lint --executable-routes` (and/or
   `revrem doctor --validate-routes`), that validates draft route fallback
   chains for implemented/compatible harnesses **regardless of**
   `routing.enabled`. Wire it through `validate_policy` / `profile_routed_harnesses`
   with an explicit `include_disabled_routes: bool` parameter rather than the
   current unconditional early-return.
2. **Add** the T4d test case: the same disabled-routing profile with an
   unimplemented draft route **fails** the requested executable validation.
   Keep the existing default-skip test as-is — it is spec-correct.
3. Keep the default (no flag, routing disabled) behavior unchanged so normal
   runs are not regressed.

### R2-2 — (MEDIUM) `--commit-message-harness` neither added nor its omission documented

T4b: "add `--commit-message-harness HARNESS` **if** commit-message drafting can
use non-Codex harnesses; **otherwise document** that only the model/prompt/effort
are currently exposed." Commit-message drafting **can** use non-Codex harnesses —
`config.commit_message_harness` is threaded into both the command builder and
executable resolution (`phase_support.py:143-145`) and through
`harnesses.prepare_prompt_invocation` (`commit.py:227`). The conditional
therefore resolves to "add the flag," but no flag exists in `cli/args.py` and no
rationale is documented anywhere. **Fix:** add `--commit-message-harness` with
CLI-over-profile precedence and a parse/precedence test, matching the triage
flags' pattern.

### R2-3 — (MEDIUM) `allow_model_escalation` boolean has no CLI override and no documented exemption

Acceptance: "Every profile/config boolean that affects the runtime loop and is
relevant to dogfood has a CLI override or a documented reason it does not." The
committed dogfood profile sets `allow_model_escalation = true`
(`.revrem.toml:58`) — a routing boolean that affects loop behavior — but there
is no `--allow-model-escalation` / `--no-allow-model-escalation` flag and no
documented exemption. **Fix:** add the negative-style boolean pair (consistent
with `--routing` / `--no-routing`) with CLI-over-profile precedence and a test,
or record an explicit, justified exemption in DEVEX-001.

### R2-4 — (MEDIUM) New triage/routing CLI flags are absent from REVREM-DEVEX-001

The DEVEX-001 v1.12 delta documents the dogfood profile, `phase_config`, and the
commit-message fallback well, but the **new operator control surface** added by
T4b is undocumented in the governed guide: `--triage` / `--no-triage`,
`--triage-contract`, `--triage-model`, `--triage-harness`,
`--triage-timeout-seconds`, `--routing` / `--no-routing`, `--routing-strict` /
`--no-routing-strict`. T4b also calls for help text "to include examples"; the
argparse `help=` strings are single-line with no examples. **Fix:** add a flag
reference (with at least the Matrix C/D examples) to DEVEX-001 and enrich the
argparse help for the boolean toggles.

### R2-5 — (LOW / quality) `display_timeout_seconds` is dead-parametrized

`config_builder.display_timeout_seconds(value, *, unbounded_when_none=False)` is
called only ever with the default `False`, making it an identity function;
the intended "`None` → `0`" behavior is instead reimplemented by four duplicated
`if x_display is None: x_display = DEFAULT_TIMEOUT_SECONDS` blocks. The helper
does not earn its abstraction and the `unbounded_when_none=True` branch is never
exercised. **Fix:** either route the explicit-`0` projection through the helper
(use the param) or inline it and delete the helper.

### R2-6 — (LOW / quality) residual call-for-side-effect in `run_commit`

`commit.py:117-118` still calls `commit_artifact_relative_path(config, repo_root)`
purely to trigger the "artifact-dir == repo-root" refusal and discards the
result — the de-fanged remnant of Round 1's B1. It is now correct (it only
raises in the legitimate refusal case), but a reader cannot tell that from a
discarded call. **Fix:** extract a named guard, e.g.
`_reject_artifact_dir_at_repo_root(config, repo_root)`, so the intent is
self-evident.

### R2-7 — (LOW) `default_route` internal-reference check was moved behind the routing-enabled gate

T4d: "Keep syntax and internal-reference validation for draft routes
**regardless of** routing enabled." The rule-level `then.route` reference check
is correctly always-on (`profiles.py:1090-1093`), but the `default_route` →
unknown-route reference check is now gated on `routing.enabled`
(`profiles.py:1095-1101`). A disabled-routing profile with
`default_route = "does-not-exist"` therefore passes validation. `default_route`
is a pure internal reference (no executable requirement), so gating it is
inconsistent with the stated invariant. **Fix:** restore the `default_route`
reference check to always-on; keep only the executable-chain walk gated.

---

## Round 2 — Definition of done for Codex

1. **R2-1** — build the on-demand executable-route validation mode; **add** the
   T4d "fails-when-requested" test; keep the existing default-skip test and
   behavior unchanged. **(blocks "complete")**
2. **R2-2** — add `--commit-message-harness` (+ precedence test).
3. **R2-3** — add the `allow_model_escalation` boolean toggle (+ test) or a
   documented exemption.
4. **R2-4** — document the new triage/routing flags in DEVEX-001 with examples;
   enrich argparse help.
5. **R2-5/6/7** — simplify `display_timeout_seconds`; extract the named
   repo-root refusal guard; restore the always-on `default_route` check.
6. Re-run the full gate in **both** `/tmp` states and update the task card with
   evidence (test names / commit refs), not a bare status flip.

---

## Round 1 — original findings (remediated; retained for history)

> Superseded by Round 2. Every blocker and medium below has been fixed and
> re-verified; see the "Round 1 closure" table above.

### Round 1 scorecard

| Axis | Verdict | Basis |
|---|---|---|
| 1. Complete | **No** | `pytest -q` is not green on a clean checkout (B1). |
| 2. Highest quality | **Partial** | Dead discarded call (`commit.py:111`) creates a hidden hard precondition; duplicated, divergent repo-root walkers (B1/B2). |
| 3. Modular / hexagonal | **Mostly yes** | `lint-imports`: 9 contracts kept, 0 broken. One real leak: `git_repo_root` reaches around the injected `runner` port to touch the real filesystem (B1). |
| 4. Properly tested | **No** | Two commit tests are non-hermetic and fail on a clean checkout; the suite is green only when an ambient `/tmp/.git` happens to exist (B1). |
| 5. Documented (Meminit DocOps) | **Partial** | Committed docs pass meminit; the gate currently fails only on a stray, prior-session artifact (M3). |
| 6. Demonstration-class | **Not yet** | Shipping a suite that cannot be green on a clean machine, and a discarded function call that doubles as a hidden precondition, is not star-senior work. The rest is close. |

---

## Reproductions (run these first — they are deterministic)

Both runs use the committed branch with no source edits.

**Repro A — clean system temp (standard CI / fresh clone):**

```bash
rm -rf /tmp/.git /tmp/.revrem.toml
./.venv/bin/python -m pytest -q
# => 2 failed, 828 passed
#    FAILED tests/test_commit_harness.py::TestCommitAdapter::test_no_staged_changes_returns_skipped_no_changes
#    FAILED tests/test_commit_harness.py::TestCommitAdapter::test_commit_failed_propagates_unchanged
#    RuntimeError: unable to determine git repository root ... commit.py:44
```

**Repro B — an ambient `.git` at the real temp root (the state Codex's env was in):**

```bash
mkdir -p /tmp/.git
./.venv/bin/python -m pytest -q
# => 4 failed, 826 passed
#    FAILED tests/test_profiles.py::test_project_config_path_ignores_bare_temp_root_git_marker
#    FAILED tests/test_cli_artifact_ignore.py::test_run_loop_creates_repo_local_revrem_gitignore_for_default_artifacts
#    FAILED tests/test_cli_artifact_ignore.py::test_run_loop_falls_back_to_workspace_gitignore_for_symlinked_default_artifacts
#    FAILED tests/test_cli_review_helpers.py::test_harness_bin_override_controls_non_codex_executable
```

**There is no state of `/tmp` in which the suite is green.** The two failure
sets are mutually exclusive on whether `/tmp/.git` exists. Codex most likely
saw green because its environment had `TMPDIR=/tmp` *and* a leftover
`/tmp/.git` from earlier dogfood runs — the one combination that masks both
defects at once.

> Note: I could not reproduce the suite *creating* `/tmp/.git` itself (a full
> clean run did not regenerate it), so I make no claim that the tests pollute
> `/tmp`. The leftover `/tmp/.git` was pre-existing in this environment. The
> findings below do not depend on that question.

---

## BLOCKERS

### B1 — Commit tests are non-hermetic; the suite cannot be green on a clean checkout

Root cause chain, all confirmed by reading source:

1. `adapters/commit.py:111` — `run_commit` calls `commit_artifact_relative_path(config)`
   **and discards the return value.** The call has no other effect, so its only
   real consequence is to force the next item to run.
2. `commit_artifact_relative_path` → `git_repo_root(config.cwd)`
   (`commit.py:40-45`) walks the real filesystem for a `.git` ancestor and
   **raises `RuntimeError`** when none is found. This is reached *before* the
   staged-changes check at `commit.py:142-151`, i.e. on the
   no-staged-changes / commit-failure paths that should never need the repo root.
3. `git_repo_root` touches the filesystem directly, **bypassing the injected
   `runner` port** — so the tests' `_git_runner` mock (which simulates every git
   subprocess) cannot intercept it.
4. `tests/test_commit_harness.py::test_no_staged_changes_returns_skipped_no_changes`
   and `::test_commit_failed_propagates_unchanged` set `cwd=tmp_path` but never
   create a `.git` there, so on a clean machine both raise instead of returning
   `skipped_no_changes` / `CommitFailed`.

Why the other 4 `TestCommitAdapter` tests pass and these 2 don't (the
discriminator): the passing tests never reach the real path — `dry_run`
short-circuits at `commit.py:106`; `test_retrying_flag_threaded_through` patches
`run_commit`; the dispatch tests use sentinels / monkeypatched `execute`. Only
these two exercise the real `execute → run_commit → git_repo_root` chain.

**Required fix (do all three — they are independent defects):**
1. **Code:** Remove the dead `commit_artifact_relative_path(config)` call at
   `commit.py:111`, or use its result. The repo-root resolution must not run on
   the skip path, and a no-op call whose only effect is to raise is a latent bug.
2. **Code/port boundary:** Route repo-root discovery through the injected
   `runner` (e.g. `git rev-parse --show-toplevel` via the port) instead of a
   private filesystem walk, **or** have it degrade gracefully (return `None`)
   rather than hard-raise, so artifact-exclusion logic can no-op when there is no
   repo. Reaching around the port is the one real hexagonal violation in this
   slice.
3. **Tests:** Make both tests hermetic — create a real git repo in `tmp_path`
   (`subprocess.run(["git","init"], cwd=tmp_path)` or the existing
   `_init_git_repo` helper) so they assert behavior, not ambient state.
4. Add a regression test that runs the commit skip path with **no** `.git`
   anywhere on the path and asserts a clean `skipped_no_changes` (proves the
   skip path never requires the repo root).

### B2 — `_repo_root` temp-root exclusion is incomplete (Repro B)

`profiles.py:145-154` (`_repo_root`, new in this branch, commit `5aa58c7`)
excludes only the *exact* directories `tempfile.gettempdir()` and
`os.environ["TMPDIR"]`. When `TMPDIR` is a *subdirectory* of `/tmp` (e.g.
`/tmp/claude-1000`), the walk still ascends into the un-excluded parent `/tmp`,
and an ambient `/tmp/.git` is wrongly accepted as the repo root — producing the
4 failures in Repro B. Two coupled problems:

- **Logic:** exclude the temp root **and all of its ancestors** (or stop the
  upward walk at the first temp root encountered), not just the literal temp dir.
- **Test seam:** `test_project_config_path_ignores_bare_temp_root_git_marker`
  monkeypatches `profiles.tempfile.gettempdir`, but the implementation
  *independently* reads `os.environ["TMPDIR"]`, so the function under test is not
  fully controlled by the test. Funnel both temp-root sources through a single
  seam the test can patch, then add a case where `TMPDIR` is a child of the
  `.git`-bearing directory.

**Also unify the two repo-root walkers.** `profiles._repo_root`
(excludes temp roots, returns `cwd` on miss) and `commit.git_repo_root` (no
exclusion, raises on miss) are duplicated logic with divergent semantics. Have
one resolver with one well-documented contract and call it from both sites.

---

## MEDIUM

### M3 — `meminit check` fails on a stray, mis-formatted artifact

`meminit check` currently returns `success:false` because of
`docs/tasks/TASK-004-adversarial-review.md` (`FRONTMATTER_MISSING` +
`FILENAME_CONVENTION`). That file is **not Codex's deliverable** — it is an
untracked prior-session artifact whose header reads "Reviewer: Claude (Opus
4.8)" and which reviews a **Node.js codebase** (`dogfood/lib/*.js`,
`HARNESS_REGISTRY`, `package.json`) that does not exist in this Python repo. It
should be **deleted**; until it is, the acceptance gate "`meminit check` passes"
is red. (This findings document is its correctly-formatted replacement.)

### M4 — DF-008 resume command is incomplete vs. spec

`runtime.py:166` `_resume_command` emits `--base`, `--profile`,
`--initial-review-file`, and conditionally `--commit-on-hook-failure`. The task
required "base, profile **or checks**, commit mode, **timeout intent**, and the
initial review file." Missing: `--timeout-seconds` (the explicit-`0` intent that
DF-006 went to such lengths to preserve is dropped from the one command an
operator copies), `--check` fallback when no profile is active, and explicit
commit mode (`--commit-after-remediation` / `--no-commit`). Add them and assert
the round-trip in a test.

### M5 — Deterministic commit fallback ignores review/remediation context

`deterministic_commit_message` (`commit.py:263`) now takes `staged_paths` and
infers scope/type from path classes only, so it can emit `fix`/`docs`/`test`
but never `feat`/`refactor`/`perf`. DF-001 explicitly asked to "infer type from
review/remediation **context** and file classes." Thread the review/remediation
summary into the type inference, or document why path-class inference is the
deliberate ceiling.

### M6 — `phase_config` source markers are coarse

`config_builder.py:315-338` marks a whole phase `source="cli"` if *any* field of
that phase was overridden, even when other fields came from the profile. For the
DF-002 "source of each phase configuration" goal, attribute source per field, or
document the phase-level granularity as intentional.

---

## What is genuinely good (keep — verified by reading source + tests)

- **DF-001 web_search disable:** `CodexHarnessAdapter` scopes
  `--disable web_search` to the `commit-message` role only (`harnesses.py:75-76`);
  tests assert both its presence for commit-message and its **absence** for
  remediation (`test_cli_review_helpers.py:645-688`). Correct and well-targeted.
- **DF-001 / T4a commit schema:** `COMMIT_KEYS` extended with
  `reasoning_effort` + `timeout_seconds`; precedence is exactly
  CLI → profile-commit → remediation/global (`config_builder.py:206-216`).
- **DF-006 explicit `0` timeout:** display/internal split is correct — `0` is
  preserved in every operator-facing projection while the subprocess layer maps
  it to unbounded (`config_builder.py:134-177`, `phase_support.phase_timeout_seconds`).
- **DF-002 phase plan:** `summary.json` carries a full normalized
  `phase_config` (review/triage/remediation/commit_message/checks +
  harness/model/effort/timeout/sandbox/source); confirmed in the committed
  snapshot.
- **DF-009 command line:** redacted argv wired at `cli/main.py:29`
  (`_redacted_argv`) and asserted in `test_cli_summary_integration.py`.
- **DF-005 latest review excerpt:** present in the findings summary snapshot.
- **T4a regression guard:** `test_project_dogfood_profile_parses_exact_committed_profile`
  parses the exact committed `[profiles.dogfood]` block under strict
  `_reject_unknown_keys`, using the corrected key names.
- **Architecture:** `ruff` clean, `mypy` clean (73 files), `lint-imports` 9/9
  contracts kept. The hexagonal boundaries hold (B1's port leak excepted).

---

## Not independently verified (scope honesty — neither pass nor fail)

I read these only at a glance; treat as unverified, not as approved:

- **T4d** routing-disabled gating semantics (DF-004) beyond confirming the
  strict-route branch exists in `policy.py`.
- **T4f** fake-harness route fallback and `--harness-bin` precedence in the
  phase plan.
- **DF-007** latest-check status table accuracy.
- **DF-010** read-only artifact-ignore no-op (claimed pre-remediated).

---

## Definition of done for Codex

1. **B1** — remove the discarded `commit.py:111` call; route repo-root through
   the `runner` port or degrade gracefully; make both commit tests hermetic; add
   the no-repo skip-path regression. **(blocker)**
2. **B2** — fix `_repo_root` to exclude temp-root ancestors; unify the two
   repo-root walkers behind one contract; fix the `gettempdir`/`TMPDIR` test
   seam. **(blocker)**
3. **Prove it:** `rm -rf /tmp/.git /tmp/.revrem.toml && pytest -q` is green, and
   `pytest -q` is *also* green with a `/tmp/.git` present. Both states must pass.
4. **M3** — delete `docs/tasks/TASK-004-adversarial-review.md`; confirm
   `meminit check` returns `success:true`. **(required)**
5. **M4–M6** — complete the resume command, enrich fallback type inference, and
   refine source markers (or document the deliberate ceilings). **(required for
   demonstration-class)**
6. Re-run the full gate: `ruff`, `mypy`, `lint-imports`, `meminit check`,
   `pytest -q` — all green — and update the task card with evidence
   (test names / commit refs), not just a status flip.
</content>
