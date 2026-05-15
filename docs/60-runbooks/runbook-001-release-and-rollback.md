---
document_id: REVREM-RUNBOOK-001
type: RUNBOOK
title: Release And Rollback
status: Approved
version: '0.2'
last_updated: '2026-05-15'
owner: GitCmurf
docops_version: '2.0'
area: release
description: Operator runbook for RevRem package release dry-runs, publishing, provenance
  checks, and rollback actions.
keywords:
- release
- pypi
- rollback
- provenance
related_ids:
- REVREM-TASK-002
- REVREM-ADR-011
---

# RUNBOOK: Release And Rollback

## Context

Use this runbook when preparing, publishing, verifying, or rolling back a
RevRem package release. It assumes the release workflow from `REVREM-ADR-011`
is present and that the maintainer has repository admin access plus PyPI owner
access.

## Content

## Preflight

1. Confirm the working tree is clean and the release branch has passed CI.
2. Run the local gate:

   ```bash
   ./scripts/dev-check
   ```

3. Confirm `pyproject.toml` and `src/code_review_loop/__init__.py` have the
   same version.
4. Confirm `CHANGELOG.md` has a release note for the target version.
5. Confirm the project page and README render cleanly on GitHub.

## One-Time Trusted Publishing Setup

Create Trusted Publisher entries in both PyPI and TestPyPI:

- owner: `GitCmurf`
- repository: `revrem`
- workflow name: `Release`
- environment: `release`
- package name: `revrem`

Do not add a long-lived PyPI token for the normal path. If an emergency token is
used, record why it was needed, where it was stored, who can access it, and when
it will be removed.

## Dry Run

Run the GitHub `Release` workflow manually with `dry_run=true`.

Expected artifacts:

- sdist;
- wheel;
- `SHA256SUMS`;
- CycloneDX SBOM;
- Sigstore signature/certificate outputs;
- GitHub build-provenance attestation.

Inspect the workflow log for:

- `python -m twine check dist/*`;
- successful version validation;
- successful build-provenance attestation;
- no PyPI or TestPyPI publish step.

## TASK-002 External Gate Checklist

These gates complete the parts of `REVREM-TASK-002` that cannot be proven from
an unpushed local branch:

1. Merge the implementation branch to `main` only after CI and required review
   checks are green.
2. Confirm branch protection requires the CI workflow before merge.
3. Run the `Release` workflow with `dry_run=true` and archive the workflow URL
   in the release issue or PR closeout note.
4. Confirm the dry-run artifact contains the sdist, wheel, `SHA256SUMS`,
   CycloneDX SBOM, Sigstore outputs, and GitHub build-provenance attestation.
5. Confirm no PyPI/TestPyPI publish step ran during dry-run mode.
6. Confirm PyPI and TestPyPI Trusted Publisher entries target owner
   `GitCmurf`, repository `revrem`, workflow `Release`, and package `revrem`.
7. Publish an RC tag to TestPyPI, install it in a clean environment, and run
   `revrem --version`, `revrem --help`, and
   `revrem doctor --format json --base main --codex-bin git` in a throwaway
   Git repository.
8. Publish the final tag only after the RC install smoke passes.
9. Confirm the GitHub Release has all artifacts attached and that checksums,
   signatures, and attestations verify.
10. Record final PyPI/TestPyPI/GitHub Release URLs in the release issue,
    changelog closeout, or PR body.

## TestPyPI Release Candidate

1. Set `__version__` and `pyproject.toml` to the PEP 440 RC version
   (`0.3.0rc1` in this example), then tag the human-readable equivalent:

   ```bash
   git tag v0.3.0-rc1
   git push origin v0.3.0-rc1
   ```

2. Wait for the `Release` workflow to complete.
3. Confirm it published only to TestPyPI.
4. Install from TestPyPI in a clean environment and verify the CLI:

   ```bash
   python -m venv /tmp/revrem-testpypi
   /tmp/revrem-testpypi/bin/python -m pip install --upgrade pip
   /tmp/revrem-testpypi/bin/python -m pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     revrem==0.3.0rc1
   /tmp/revrem-testpypi/bin/revrem --version
   /tmp/revrem-testpypi/bin/revrem --help
   ```

## Final PyPI Release

1. Confirm the RC checks are acceptable.
2. Tag the final version:

   ```bash
   git tag v0.3.0
   git push origin v0.3.0
   ```

3. Wait for the `Release` workflow to complete.
4. Confirm the package appears on PyPI.
5. Confirm the GitHub Release contains the artifacts, `SHA256SUMS`, SBOM, and
   signing/provenance outputs.
6. Install from PyPI in a clean environment:

   ```bash
   python -m venv /tmp/revrem-pypi
   /tmp/revrem-pypi/bin/python -m pip install --upgrade pip
   /tmp/revrem-pypi/bin/python -m pip install revrem==0.3.0
   /tmp/revrem-pypi/bin/revrem --version
   /tmp/revrem-pypi/bin/revrem --help
   ```

## Provenance Checks

For operator-level verification:

1. Download the release artifacts and `SHA256SUMS`.
2. Verify checksums:

   ```bash
   sha256sum --check SHA256SUMS
   ```

3. Inspect the GitHub attestation from the release workflow.
4. Verify Sigstore signatures with the certificate identity expected for the
   GitHub Actions workflow.

## Rollback Decision

Use this table before acting:

| Situation | Action |
|---|---|
| Install is broken for most users | Yank the release, cut a hotfix, mark GitHub Release superseded |
| Security or privacy defect | Yank immediately, publish advisory or SECURITY note as appropriate, cut hotfix |
| Documentation-only error | Edit docs or release notes; do not yank unless install guidance is actively harmful |
| Minor runtime bug with workaround | Document workaround, cut patch release; yank only if continued installs are risky |

## Yank A Bad PyPI Release

Yanking prevents new dependency resolution from selecting the version while
leaving exact pins installable.

```bash
python -m pip install --upgrade twine
python -m twine yank revrem==0.3.0
```

Record the reason in `CHANGELOG.md` and in the GitHub Release body.

## Supersede GitHub Release

1. Edit the GitHub Release title/body.
2. Add a visible note: `Superseded by vX.Y.Z because ...`.
3. Keep artifacts attached for auditability unless they contain leaked secrets.
4. Link to the hotfix release when available.

## Cut A Hotfix

1. Fix the defect on a release branch or `main`.
2. Add regression tests.
3. Update `CHANGELOG.md`.
4. Bump the patch version.
5. Run `./scripts/dev-check`.
6. Publish an RC to TestPyPI when time permits.
7. Publish the final hotfix tag.

## Post-Release Closeout

- Confirm PyPI, GitHub Release, README badges, and install commands agree.
- Confirm Dependabot/security alerts are quiet or triaged.
- Open follow-up issues for any manual release friction.

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.2 | 2026-05-13 | Codex | Added explicit TASK-002 external gate checklist |
| 0.1 | 2026-05-13 | GitCmurf | Initial release and rollback runbook |
