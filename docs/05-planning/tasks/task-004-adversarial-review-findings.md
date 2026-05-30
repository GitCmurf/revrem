---
document_id: REVREM-REVIEW-004
type: TASK
title: Adversarial review findings for TASK-004 dogfood hardening
status: Draft
version: '1.6'
last_updated: '2026-05-30'
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

> **This document has six rounds.** Round 6 (immediately below) is the current,
> authoritative re-evaluation after the Round-5 polish pass was declared
> complete. Earlier rounds are retained for history; **all Round 1–5
> blockers/mediums are remediated** and re-verified.

> **Codex remediation status (2026-05-30):** Round 4 findings R4-1 through
> R4-5 are remediated. Round 5 findings R5-1 and R5-2 are remediated, and R5-3
> is covered by a credential-gated live smoke (`REVREM_LIVE_CODEX=1`).

---

## Round 6 — re-evaluation after Round-5 polish declared complete (2026-05-30)

**Reviewer:** Claude Opus 4.8 (adversarial). **Method:** independent
re-derivation against the working tree on `fix/revrem-dogfood-first` @ `19a7441`,
not a re-read of Codex's self-report. Every claim below was reproduced from a
command captured in this review.

### Verdict by required dimension

| Dimension | Verdict | Basis |
|-----------|---------|-------|
| 1. Complete | **No — one item open (F1)** | Headline acceptance "Codex-only dogfood matrix passes" / "trust commits produced by the loop" is proven only by dry-run + argv-shape assertions; no real loop or live model call has ever run. |
| 2. Highest quality | **Mostly yes** | Provenance/visibility work is excellent; residual taste defects in the deterministic fallback (F2/F3/F5). |
| 3. Modular / hexagonal | **Yes, with one placement smell** | Import contracts (9 kept) and the phase-plan projection are clean; model-capability knowledge is misplaced in the CLI layer (F4). |
| 4. Properly tested | **No — coverage shallower than changelog claims** | Suite is green (848) but a round-5 "forbidding verb-doubling" claim is not actually enforced by its test, and the headline live path is untested (F1, F6). |
| 5. Fully documented (DocOps) | **Yes** | `REVREM-DEVEX-001` documents the full triage/routing/commit surface; `meminit check` → `success:true` (29 files). |
| 6. Demonstration-class | **Not yet** | One green-gate-invisible test-honesty gap (F6) and an unrun headline deliverable (F1) are exactly what a star senior dev would not ship as "done." |

### Verified green (reproduced, not trusted)

- `ruff check .` ✓ · `mypy src` ✓ (74 files) · `lint-imports` ✓ (9 contracts kept,
  0 broken) · `meminit check --format json` ✓ (`success:true`, 29 files).
- `pytest -q` **848 passed / 1 skipped** in a **clean** `/tmp` *and* **848 passed**
  with a polluted `/tmp/.git` + `/tmp/.revrem.toml`. Round-1/2 hermeticity holds.
- **DF-002/DF-006 (excellent):** `phase_config` carries field-level `sources`
  provenance with an explicit `source: "mixed"` marker when a CLI flag overrides
  one field of an otherwise-profile phase, and explicit `timeout_seconds = 0.0`
  survives into operator-facing projections. Reproduced via
  `revrem --profile dogfood --no-routing --dry-run --summary-format json`.
- **DF-003 (Matrix D):** `--triage --triage-contract v2 --routing` flips triage
  and routing on with no profile edit.
- **DF-004 (Matrix F):** the `dogfood` profile (which carries a route table)
  resolves cleanly under `--no-routing`; no executable-route chain check fires.
- **DF-001 command shape:** `commit-message` role emits
  `-c web_search="disabled"`; positive *and* negative tests
  (`test_remediation_command_does_not_disable_web_search`) lock the scoping.
- **DF-005 / DF-007 / DF-008:** `latest_review_excerpt` is populated on a
  `findings` outcome; the JSON summary carries a per-check status table
  (`command`/`artifact`/`status`); terminal closeout prints a full
  copy-pasteable `Continue command:` preserving `--profile`, `--no-routing`,
  `--commit-after-remediation`, `--initial-review-file`, and hook policy.

This is genuinely strong work. The findings below are residual, not a re-opening.

### F1 — BLOCKER (for "complete" + "properly tested"): the headline deliverable has never actually run

- **Evidence:** every recorded `dogfood` run under `.revrem/runs/` is `--dry-run`
  (`20260530T023305Z`, `20260530T004018Z`, and the two I just produced). The
  one credential-gated live test (`tests/test_live_codex_commit_message.py`) is
  **skipped** in every gate run shown (`REVREM_LIVE_CODEX` unset).
- **Why it's not closed by the green suite:** the task's own acceptance says
  *"Codex-only dogfood matrix passes"* and *Done means … trust commits produced
  by the loop.* Neither is demonstrated. Matrix A
  (`revrem --profile dogfood --base main --max-iterations 3`, **no** `--dry-run`)
  has never executed end-to-end; no real commit produced by the loop exists as
  evidence.
- **Sharper still:** even if the live smoke *were* run, it constructs the config
  with `commit_reasoning_effort="low"` (the **already-promoted** state for
  `gpt-5.3-codex-spark`). So it validates the `minimal→low` promotion path — it
  does **not** demonstrate the actual DF-001 thesis that
  `web_search="disabled"` lets a genuine `reasoning.effort=minimal` request
  through. That raw claim is proven only by argv shape, never by a live 200.
- **This is an operator action, not a Codex code task.** Five rounds have
  converted this into "operator sign-off"; per the no-deferral instruction it is
  named here as the one open item. It clears by *running*, not by more code:

  ```bash
  # 1. headline matrix — must produce real, specific commits
  ./.venv/bin/revrem --profile dogfood --base main --max-iterations 3
  # 2. raw DF-001 thesis — minimal must NOT 400 with web_search disabled
  REVREM_LIVE_CODEX=1 REVREM_LIVE_CODEX_COMMIT_MODEL=gpt-5.5 \
    ./.venv/bin/pytest -q tests/test_live_codex_commit_message.py
  ```
  Recommendation for Codex/the live smoke: add a variant that sends a true
  `commit_reasoning_effort="minimal"` to a model **not** in the promotion set,
  so the suite actually exercises "minimal survives because the tool is
  disabled" rather than only the promotion detour.

### F6 — REQUIRED (test honesty): round-5 "verb-doubling" claim is not enforced

- **Claim (round-5 evidence):** *"added property-style fallback tests forbidding
  verb-doubling and scope/type collisions."*
- **Reality:** `test_deterministic_commit_message_strips_redundant_type_verbs`
  asserts only **leading-position** trigger-verb removal plus noun presence. It
  does not cover interior trigger verbs or repeated nouns, so the claim is
  overstated relative to the test.
- **Proof (reproduced):**
  `deterministic_commit_message(2, staged_paths=["src/code_review_loop/cli/args.py"],
  context="Add a new --triage flag to enable triage from the CLI.")` →
  `feat(code-review-loop): triage flag enable triage (RevRem)` — interior verb
  `enable` retained and noun `triage` doubled.
- **Fix:** strip trigger verbs anywhere in the summary token list (not only
  index 0) and de-duplicate repeated tokens; add a property test over the
  interior-verb / duplicate-noun case so the changelog and the test agree.

### F2 — REQUIRED (taste): fallback summaries read awkwardly

Same root cause as F6. Beyond verb-doubling, the 4-token noun window produces
phrases like `some vague change words` for low-information context. Tighten the
`_noun_from_text` selection (drop residual trigger/filler words mid-phrase;
prefer the first contiguous noun phrase) so degraded-path subjects stay crisp.

### F3 — REQUIRED (taste): file-name-derived scopes leak as low-signal scopes

- **Proof:** `["README.md"]` → `docs(readme-md): document README`;
  `["x.txt"]` → `chore(x-txt): some vague change words`.
- Round 5 committed to suppressing low-value scopes (`docs(docs)`, one-char).
  `readme-md` / `x-txt` are *filename slugs* masquerading as package scopes.
- **Fix:** in `_commit_scope`, when the dominant first path segment is a **file**
  (has a suffix) rather than a directory, suppress the scope instead of slugging
  the filename. Extend `_is_low_signal_scope` accordingly.

### F4 — REQUIRED (modularity): model-capability knowledge lives in the CLI layer

- `_CODEX_MINIMAL_UNSUPPORTED_COMMIT_MODELS = frozenset({"gpt-5.3-codex-spark"})`
  sits in `cli/config_builder.py`. "Which Codex model rejects which
  `reasoning.effort`" is **harness/model-capability** domain knowledge, not
  CLI-argument-assembly knowledge.
- For the stated hexagonal bar, this predicate belongs with the Codex harness
  adapter (e.g. a `codex` capability helper the adapter owns) so the CLI edge
  *asks* "does this model support minimal?" rather than *encoding* the model
  fact. Round-5's narrowing was correct for behaviour; only the placement is the
  smell. Move the registry + predicate down a layer and have `config_builder`
  call it.

### F5 — POLISH (scope signal): every `src/` change collapses to one scope

- **Proof:** `_src_scope` returns `code-review-loop` for `cli/args.py`,
  `adapters/commit.py`, and `core/ports.py` alike — because it stops at
  `parts[1]` (the single top package). In a one-package repo the scope is
  near-constant and therefore uninformative.
- **Fix:** drill one segment deeper for `src/<pkg>/<subpkg>/...` paths so scopes
  become `cli`, `adapters`, `core`, etc. — materially more useful, and it makes
  the fallback subjects look authored rather than templated.

### Handback summary

- **To Codex (code):** F2, F3, F4, F5, and **F6** (fix the test *and* the
  implementation so the changelog claim is true). All are bounded, strictly
  in-scope quality improvements — no deferral.
- **To the operator (run, not code):** F1 — execute Matrix A and the live
  `REVREM_LIVE_CODEX=1` smoke (with the minimal-on-non-promoted-model variant)
  and attach the resulting run/evidence artifact. Until that exists, "Codex-only
  dogfood matrix passes" remains an assertion, not a fact.

### Round 6 — definition of done

1. **F6/F2** — strip trigger verbs at any position, de-dupe tokens, tighten the
   noun window; replace the leading-only assertion with an interior-case
   property test. **(required)**
2. **F3** — suppress filename-derived scopes for repo-root single files.
   **(required)**
3. **F4** — relocate the Codex `minimal`-unsupported predicate to the harness
   layer; `config_builder` queries it. **(required)**
4. **F5** — deepen `_src_scope` to the sub-package segment. **(polish)**
5. **F1** — operator runs Matrix A + the live minimal smoke; evidence artifact
   committed and cited on the task card. **(blocks "complete"; not a Codex task)**
6. Re-run the full gate in both `/tmp` states and update the task card with test
   names / commit refs, not a status flip.

---

## Round 5 — re-evaluation with live DF-001 exercise (2026-05-30)

- **Reviewer:** Claude (Opus 4.8), adversarial re-evaluation. This round
  departs from prior rounds by running the **real Codex 0.135.0 CLI** for the
  commit-message role instead of only asserting generated command shape.
- **Verdict:** **Code-complete and mergeable. Not a sixth round of blockers.**
  All five gates pass and are hermetic across clean and polluted `/tmp`
  (`845 passed` in each state, re-verified this round). Architecture is strong
  (hexagonal ports/adapters, 9/9 import contracts kept). DF-001 — the finding
  that *originated this entire task* — is now **proven live** for the first
  time, closing the largest residual risk. Two real quality findings and one
  durability improvement remain; none blocks merge.

### What was verified live (new evidence prior rounds lacked)

- **DF-001 fix works end-to-end.** The exact adapter-built command
  `codex exec -c model_reasoning_effort="low" -c web_search="disabled" --sandbox read-only --color never --model gpt-5.3-codex-spark -`
  returned **exit 0** with a clean professional subject
  (`chore(harness): disable web search for commit-message role`) — the direct
  inverse of the original `commit-2-message-draft.txt` HTTP 400 artifact.
- **The `minimal -> low` promotion is genuinely necessary** — but for a reason
  the code mis-states (see R5-1). Live `minimal` still returns HTTP 400.
- **Resume command (DF-008) is demonstration-class.** `runtime._resume_command`
  carries base, max-iterations, profile/checks, timeout, the full
  review/remediation/commit/triage/routing override surface, commit mode, and
  hook policy, shell-quoted via `shlex.join`, emitting overrides only when they
  diverge from the profile. No finding.

### R5-1 [Major — operator truthfulness] Promotion label/comment misattribute the cause

- **Observed (live).** With `web_search="disabled"` already applied,
  `model_reasoning_effort="minimal"` on `gpt-5.3-codex-spark` returns:
  `Unsupported value: 'minimal' is not supported with the
  'gpt-5.3-codex-spark-1p-codexswic-ev3' model. Supported values are: 'low',
  'medium', 'high', and 'xhigh'.` (`status: 400`, `param: reasoning.effort`).
- **Defect.** This is a **model-level** capability gap, not tool incompatibility.
  Yet `config_builder.py:215-220` promotes with comment *"Codex 0.135.0 still
  injects built-in tools that are incompatible with minimal reasoning"* and the
  operator-visible `phase_config.commit_message.reasoning_effort_adjustment`
  label is `codex_minimal_tool_incompatibility`. After web_search is disabled,
  no tool is the cause — the model simply does not accept `minimal`. An operator
  reading the provenance is actively misled, which is precisely the
  operator-truthfulness bar Round 4 set.
- **Required remediation:**
  1. Rename the adjustment to a model-accurate token, e.g.
     `codex_minimal_unsupported_by_model` (and update reporting/resume
     projections + tests that assert the old string).
  2. Rewrite the `config_builder.py` comment to state the model-capability
     reason, optionally noting that disabling `web_search` was the *separate*
     fix for the original tool-level 400.
  3. The promotion is currently hardcoded for **all** Codex commit models
     (`commit_message_harness == "codex" and effort == "minimal"`), but the
     constraint is model-specific. Either document this as a deliberate
     conservative blanket promotion, or gate it on known-incompatible models so
     a future Codex model that supports `minimal` is not silently overridden.

### R5-2 [Medium — fallback taste; repeat theme of Rounds 3 & 4] Ungrammatical/redundant fallback subjects

- **Observed (live function output, `deterministic_commit_message`):**
  - `fix(code-review-loop): fix preserve latest excerpt unresolved (RevRem)` — verb doubling (`fix … preserve`)
  - `refactor(foo): refactor extract duplicated subprocess runner (RevRem)` — verb doubling
  - `test(tests): cover add coverage escalation precedence (RevRem)` — triple redundancy
  - `docs(docs): document new triage controls (RevRem)` — scope equals type
  - `perf(a): improve performance cache repeated rev-parse (RevRem)` — redundant `improve performance` + single-letter scope `a`
- **Root cause.** (a) `_noun_from_text` (`commit.py:431`) does not strip the
  type-triggering verb/synonym from the noun phrase, so the Conventional-Commit
  type verb collides with the noun's leading word. (b) No suppression when
  `scope == type` or when scope is a non-informative single segment. The Round-4
  property tests assert Conventional-Commit *shape* only, so these all pass.
- **Required remediation:**
  1. In `_noun_from_text`, drop a leading word that is the type verb or a known
     synonym of it (extend the existing `stop_words`/verb logic).
  2. In `_commit_scope`, suppress scope when it equals the resolved type
     (`docs(docs)`) or is a single low-signal token.
  3. Add property tests forbidding `^(\w+)(\(.+\))?: \1\b` verb-doubling and
     `(\w+)\(\1\)` scope==type collisions.
- **Severity note.** Last-resort fallback only; the literal acceptance criterion
  ("fallback never emits generic iteration-only subjects") **is** met. Polish,
  not a blocker.

### R5-3 [Minor — durability] Convert the one-time DF-001 matrix into a continuous live smoke

- The DF-001 path is exercised by command-shape unit tests plus this round's
  manual live run. To stop DF-001 from silently regressing against future Codex
  releases, add a **credential-gated** live smoke (skipped when `codex` or creds
  are absent) that drafts a commit subject for the current staged diff through
  the real harness and asserts a non-empty, non-error subject. This converts the
  credential-gated Matrix A/C/E from a one-time operator sign-off into durable
  CI-optional verification.
- Also folds in over-eager `fix` classification: `_commit_type` fix patterns
  (`error|fail|correct|broken|…`) match almost any review-derived context,
  biasing most fallbacks to `fix`. Tighten alongside R5-2.

### Round 5 scorecard

| Dimension | Verdict | Evidence |
|---|---|---|
| 1. Complete | **Yes** | All acceptance criteria met; DF-001 proven live this round. |
| 2. Highest quality | **Mostly** | R5-1 provenance mislabel and R5-2 fallback taste are the remaining gaps. |
| 3. Modular / hexagonal | **Yes** | 9/9 import contracts kept; ports/adapters intact. |
| 4. Tested | **Yes, with a gap** | `845 passed` × both `/tmp` states; R5-3 would close the live-evidence gap durably. |
| 5. Documented (DocOps) | **Yes** | `meminit check` 29/29 OK. |
| 6. Demonstration-class | **Yes, after R5-1/R5-2** | Resume command, phase_config provenance, and dry-run plan are exemplary; fallback taste and the mislabel are the only things short of star-senior bar. |

---

## Round 4 — re-evaluation after final operator-polish remediation (2026-05-30)

- **Reviewer:** Claude (Opus 4.8), adversarial re-evaluation against the
  reputation-at-stake dogfood bar.
- **Verdict:** **Architecturally strong, with one blocker and four narrow
  quality gaps before final dogfood sign-off.** The blocker is taste and
  portability: fallback commit subjects must not inject RevRem-specific canned
  vocabulary into arbitrary target repositories.
- **Required remediations:** R4-1 repository-generic deterministic commit
  fallback; R4-2 operator-visible Codex `minimal -> low` effort promotion;
  R4-3 broad command-line redaction; R4-4 field-level `routing_strict`
  provenance through real config construction; R4-5 neutral fallback type
  defaults to `chore`.
- **Verification note:** The implementation must keep property-style fallback
  tests rather than fixture-reversed exact strings, and it must verify
  configuration projections from `build_loop_config` state rather than
  hand-authored summary dictionaries. Live Matrix A/C/E remains credential
  gated and is the operator sign-off after the local gates pass.

## Round 3 — re-evaluation after route-validation remediation (2026-05-29)

- **Reviewer:** Claude (Opus 4.8), adversarial re-evaluation against the TASK-004
  dogfood hardening bar.
- **Verdict:** **Complete and architecturally strong, but not yet
  demonstration-class until final polish lands.** The remaining gap is narrow:
  fallback commit subjects are still semantically weak, commit-type inference
  can over-label fixes as `feat`, suggested resume commands drop the newly
  added triage/routing override surface, and wrapped compact progress lines
  omit the line prefix that makes them grep-friendly.
- **Required remediations:** F1 descriptive fallback subject synthesis; F2
  bugfix-first commit-type inference; F3 complete resume override projection;
  F4 closeout phase-config `source=` visibility; F5 no subset-like check
  artifact fallback on parse miss; F6 prefixed wrapped progress lines; F7
  documented temp-root ancestor exclusion.
- **Verification note:** Matrix A/C/E require live Codex/Gemini credentials.
  The `--commit-reasoning-effort minimal` fix is structurally verified by the
  scoped `-c web_search="disabled"` command shape; a real Codex Matrix C run
  remains the operator proof after gates pass. Later live exercise showed
  `gpt-5.3-codex-spark` rejects `minimal` at the model-capability layer, so the
  implementation promotes that known incompatible commit-message model to
  `low`.

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
  Matrices D and F end-to-end; verified the then-planned search-disable command
  shape; traced each finding to a specific source line.
  Note on DF-001: the "`--commit-reasoning-effort minimal` succeeds" criterion
  is verified here by command-shape assertion (the scoped search-disable
  override is present), not by a live commit-message model call —
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
  `-c web_search="disabled"` to the `commit-message` role only (`harnesses.py:75-76`);
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
