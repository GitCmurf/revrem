# Contributing

Thanks for considering a contribution to `code-review-loop`. This project is a
local automation tool for watched AI-assisted review/remediation loops, so
changes need to preserve operator visibility, bounded execution, and artifact
traceability.

## Local Setup

```bash
git clone https://github.com/GitCmurf/revrem.git
cd code-review-loop
./scripts/install-dev
pre-commit install
```

Meminit is this repository's governed documentation system. It validates the
structured documents under `docs/` and keeps planning, architecture, testing,
and operator guidance consistent with code changes. Install Meminit before
running the full local gate:

```bash
python -m pip install "meminit @ git+https://github.com/GitCmurf/meminit.git@63547bc79f46200d25e4b7375b5c661f64aa34f8"
```

## Required Checks

Run these before opening a pull request:

```bash
./scripts/dev-check
pre-commit run --all-files
meminit check --format json
git diff --check
```

Security-sensitive changes should also run:

```bash
git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline
gitleaks detect --source . --redact
```

`gitleaks` is optional locally, but the launch checklist requires an
equivalent history-aware scanner before the repository is made public.

## Pull Request Expectations

Each PR should be one coherent unit of code, tests, and documentation. Update
governed docs when behavior, operator workflow, release process, security
posture, or architecture changes. Keep runtime dependencies out unless they
remove clear operational risk.

Pull requests should include:

- a concise behavior summary;
- test and DocOps commands run locally;
- security/privacy impact notes;
- any compatibility or migration notes;
- links to related issues or Meminit document IDs.

The preferred merge policy is squash merge after required checks and at least
one approving review. This keeps public history readable while preserving the
full PR discussion.

## Review-Loop Guidance

RevRem can be used as a pre-PR gate for this repository, but it does not
replace human review:

```bash
revrem \
  --base main \
  --max-iterations 2 \
  --check "./scripts/dev-check" \
  --check "pre-commit run --all-files" \
  --check "git diff --check"
```

Inspect the resulting diff and `.revrem/runs/<timestamp>/` artifacts before
committing any remediation.

## Roadmap And Debt

Public, contributor-actionable work belongs in GitHub Issues with labels such
as `bug`, `enhancement`, `docs`, `debt`, `good first issue`, and
`help wanted`. Internal sequencing and design rationale belong in governed
Meminit documents under `docs/`. When useful, link public issues back to
stable Meminit document IDs such as `REVREM-TASK-001`.

## Release Process

Release work should update `CHANGELOG.md`, bump the version in
`pyproject.toml` and `src/code_review_loop/__init__.py`, pass the local and CI
gates, and create a signed Git tag. Public artifacts should be produced by the
GitHub release workflow so provenance attestations and SBOM assets are
available.

Consumers can verify release artifacts with:

```bash
gh attestation verify <artifact-path> --repo GitCmurf/revrem
```
