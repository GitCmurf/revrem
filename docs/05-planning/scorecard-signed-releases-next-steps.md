---
document_id: REVREM-PLAN-006
type: PLAN
title: Scorecard "Signed-Releases" — next steps (handoff)
status: Draft
version: '0.2'
last_updated: '2026-06-24'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Status note for the OpenSSF Scorecard signed-releases work — PR #33 and v0.5.0 release-asset proof are complete; Scorecard re-evaluation and real SLSA provenance remain.
keywords:
  - scorecard
  - signed-releases
  - sigstore
  - slsa
  - security
---

# Scorecard "Signed-Releases" — next steps (handoff)

_Last updated: 2026-06-24. Updated after the v0.5.0 release._

## Where things stand

The OpenSSF **Scorecard check now runs GREEN** on `main` (run 27799999977). It
took three layered fixes, all merged:

1. PR #30 — top-level `permissions:` made read-only, write scopes (`id-token`,
   `security-events`) moved to job scope. (Fixed "global perm is set to write".)
2. PR #31 — repinned `ossf/scorecard-action` `f2ea147…` → `05b42c624433…`
   (the real `v2.4.2` commit). The old SHA was an imposter (API: "No commit found").
3. PR #32 — repinned `github/codeql-action/upload-sarif` `b1722c1…` →
   `ce28f5bb42b7…` (real `v3.29.0`), same imposter-commit class.

A full audit confirmed those two security actions were the **only** bogus pins;
all 10 action pins across all workflows are now canonical.

## Current status

- **PR #33** (`feat/scorecard-signed-releases`) merged on 2026-06-19.
- The `v0.5.0` release on 2026-06-24 proved the workflow change on a real tag.
  The GitHub Release includes both canonical `*.sigstore.json` bundles and
  Scorecard-recognised `*.sigstore` copies for the wheel, sdist, SBOM, and
  `SHA256SUMS`.
- `sha256sum --check SHA256SUMS` passed for the downloaded `v0.5.0` release
  artifacts.
- The latest observed Scorecard run still predates the `v0.5.0` release, so
  Scorecard has not yet re-evaluated the new assets.

## Remaining work (pick up here)

### 1. Wait for Scorecard re-evaluation

The release asset side is complete. The remaining proof is a Scorecard run that
starts after the `v0.5.0` release publication timestamp and observes the
`*.sigstore` assets.

Check:

```bash
gh run list -R GitCmurf/revrem --workflow "OpenSSF Scorecard" --limit 3
```

The expected outcome is that `Signed-Releases` moves from 0 toward 8.

### 2. (Optional, low value) Backfill the existing v0.4.0 release

This is no longer needed for future releases because `v0.5.0` already contains
recognised `*.sigstore` assets. Only do this if historical `v0.4.0` credit is
still useful. The v0.4.0 release has these signed bundles:
`revrem-0.4.0-py3-none-any.whl.sigstore.json`,
`revrem-0.4.0.tar.gz.sigstore.json`,
`revrem-sbom.cdx.json.sigstore.json`,
`SHA256SUMS.sigstore.json`.

Procedure (run from anywhere with `gh` authed):
```bash
tmp=$(mktemp -d); cd "$tmp"
gh release download v0.4.0 -R GitCmurf/revrem -p '*.sigstore.json'
for f in *.sigstore.json; do cp "$f" "${f%.json}"; done   # X.sigstore.json -> X.sigstore
gh release upload v0.4.0 -R GitCmurf/revrem *.sigstore
```
Note: this is an external write under the user's identity — the auto-mode
classifier may require the user to run it (it allowed `gh release edit` earlier
but blocked `gh issue create` / thread resolves, so be ready to hand the
command to the user).

### 3. (Bigger, for score 10) Real SLSA provenance as `*.intoto.jsonl`
The `*.sigstore` copies get signed-releases to ~8. The final 2 points need a
provenance file named `*.intoto.jsonl` attached to the release.
- The repo already runs `actions/attest-build-provenance`, but that publishes a
  GitHub attestation, NOT a release asset, so Scorecard doesn't see it.
- **Do NOT** just rename a bundle to `*.intoto.jsonl` — that's a misnamed,
  dishonest artifact and contradicts the cleanup this work is about.
- Legitimate path: add `slsa-framework/slsa-github-generator` (the Python /
  generic generator) to produce a real SLSA provenance `*.intoto.jsonl` and
  attach it to the GitHub release. This is a non-trivial workflow addition;
  scope it on its own.

## How to verify after a release

After tagging a version and the release workflow runs:
```bash
gh release view <tag> -R GitCmurf/revrem --json assets -q '.assets[].name'   # expect *.sigstore present
# then wait for the scheduled/post-push Scorecard run and check signed-releases:
gh run list -R GitCmurf/revrem --workflow "OpenSSF Scorecard" --limit 1
```
The Scorecard `Signed-Releases` check should move from 0 → 8 (→ 10 once SLSA
provenance is added).

## Key facts worth remembering
- Scorecard signed-releases recognised suffixes: `*.minisig`, `*.asc`, `*.sig`,
  `*.sign`, `*.sigstore`, `*.intoto.jsonl` (NOT `*.sigstore.json`).
- "Imposter commit" = a pinned action SHA not reachable from a tag/branch of the
  canonical action repo; Scorecard's publish step rejects it. Verify a pin with
  `gh api repos/<owner>/<repo>/commits/<sha>` (422 = bogus) and find the real
  tag SHA via `gh api repos/<owner>/<repo>/git/refs/tags/<tag>` (deref if
  annotated).
- Other modest score items still at 0 and why: Branch-Protection (needs admin
  PAT to read), Pinned-Dependencies=3 (pip installs not hash-pinned),
  Maintained/Contributors/CII/Fuzzing/SAST (new/solo-project signals).
