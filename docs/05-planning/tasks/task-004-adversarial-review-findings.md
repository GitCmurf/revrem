---
document_id: REVREM-REVIEW-004
type: TASK
title: Adversarial review findings for TASK-004 dogfood hardening
status: Draft
version: '1.0'
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

- **Reviewer:** Claude (Opus 4.8), adversarial re-evaluation against the 6 axes.
- **Verdict:** **NOT complete. Do not mark done.** The architecture and the
  headline dogfood features are genuinely strong, but the acceptance criterion
  "`pytest -q` passes" is **false on a clean checkout**, and is false in a
  reproducible, environment-independent way. Two correctness/quality defects sit
  directly under that failure.
- **Method:** Read the committed source for every named DF item; ran `ruff`,
  `mypy`, `lint-imports`, `meminit check`, and `pytest -q`; reproduced the test
  failures from two distinct `/tmp` states; pinned each failure to a specific
  line of production or test code.

---

## Scorecard

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
