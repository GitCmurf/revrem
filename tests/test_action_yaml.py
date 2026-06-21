"""YAML structure tests for the GitHub Action (PLAN-005 T4).

Validates that ``action.yml`` and the dogfood workflow parse as YAML and carry
the structural contract the comment-before-fail ordering and redaction model
depend on: the action maps the result LAST, gates the comment on fork mode,
and runs revrem headless with a JSON summary to stdout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    with open(ROOT / path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_action_yml_parses_and_has_composite_runs():
    data = _load("action.yml")
    assert data["name"] == "revrem"
    assert data["runs"]["using"] == "composite"
    assert isinstance(data["runs"]["steps"], list)
    assert len(data["runs"]["steps"]) >= 6


def test_action_declares_required_inputs():
    inputs = _load("action.yml")["inputs"]
    for required in (
        "base",
        "profile",
        "comment",
        "upload-artifacts",
        "raw-artifacts",
        "fail-on-findings",
        "install-mode",
    ):
        assert required in inputs, f"missing input {required}"


def test_action_install_modes_are_pypi_and_local():
    install = _load("action.yml")["inputs"]["install-mode"]
    assert "pypi" in install["default"]
    desc = install["description"].lower()
    assert "local" in desc and "pypi" in desc


def test_action_runs_revrem_headless_with_json_summary():
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    script = run_step["run"]
    assert "--no-tty" in script
    assert "--progress-style compact" in script
    assert "--summary-format json" in script
    # stdout is pure JSON; never --summary-format both in the action.
    assert "--summary-format both" not in script


def test_action_discovers_run_dir_from_json_not_globbing():
    """The two-stage guard reads artifact_dir from the JSON stdout, not .revrem/runs/."""
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    script = run_step["run"]
    assert "artifact_dir" in script
    assert ".revrem/runs" not in script


def test_action_splits_checks_safely():
    """checks input is split into repeated --check flags, never interpolated as one string."""
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    script = run_step["run"]
    assert "while IFS=" in script
    assert '--check "$line"' in script


def test_action_comment_step_gated_on_fork_mode():
    """Fork PRs skip the comment but still run/report/upload."""
    steps = _load("action.yml")["runs"]["steps"]
    comment_step = next(s for s in steps if s.get("name") == "Post PR comment")
    condition = comment_step["if"]
    assert "fork" in condition
    assert "head.repo.fork" in condition


def test_action_fork_guard_compares_to_boolean_not_string():
    """The fork guard must compare to the boolean `false`, not the string
    'true' (GPT review #5 / Sec-1): `fork != 'true'` always evaluates true under
    GitHub Actions' type coercion, so the guard never fires."""
    steps = _load("action.yml")["runs"]["steps"]
    comment_step = next(s for s in steps if s.get("name") == "Post PR comment")
    condition = comment_step["if"]
    assert "head.repo.fork == false" in condition
    assert "!= 'true'" not in condition


def test_action_docs_agree_with_fork_guard():
    """The DevEx doc must document the same fork-guard expression the action
    uses (GPT review #5) — they drifted once already."""
    doc = (ROOT / "docs/70-devex/devex-001-using-code-review-loop.md").read_text(
        encoding="utf-8"
    )
    assert "head.repo.fork == false" in doc
    assert "head.repo.fork != 'true'" not in doc


def test_action_inputs_are_not_interpolated_into_run_scripts():
    """SECURITY (GPT review #1): no `${{ inputs.* }}` may appear inside a `run:`
    script — every input must be passed via `env:` and read as a shell variable,
    or it is a script-injection vector."""
    steps = _load("action.yml")["runs"]["steps"]
    offenders = [
        s.get("name")
        for s in steps
        if isinstance(s.get("run"), str) and "${{ inputs." in s["run"]
    ]
    assert not offenders, (
        f"steps interpolate inputs directly into run scripts: {offenders}"
    )


def test_action_wires_github_token_via_input():
    """The comment step receives the token from the github-token input, not an
    unset env var (P0-3). Composite actions can't read secrets, so the caller
    passes github.token in; the input defaults to ${{ github.token }}."""
    data = _load("action.yml")
    assert "github-token" in data["inputs"]
    # Default is the automatic github.token, so the dogfood workflow needs no
    # extra secret wiring.
    assert "github.token" in str(data["inputs"]["github-token"]["default"])
    steps = data["runs"]["steps"]
    comment_step = next(s for s in steps if s.get("name") == "Post PR comment")
    token_env = comment_step["env"]["GITHUB_TOKEN"]
    assert "inputs.github-token" in token_env, (
        "GITHUB_TOKEN must come from the github-token input; "
        f"got {token_env!r}"
    )
    # Must NOT reference an unset env var (the original bug).
    assert "env.GITHUB_TOKEN" not in token_env
    # Falls back to github.token so the token resolves even if expression
    # evaluation inside the input default is not honoured (GPT review #2).
    assert "github.token" in token_env


def test_action_exit_mapping_is_last_step():
    """The exit-code mapping applies AFTER render/upload/comment."""
    steps = _load("action.yml")["runs"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert names.index("Map exit code") == len(names) - 1
    map_step = steps[-1]
    map_script = map_step["run"]
    # exit 3 -> budget ceiling; exit 2 -> fail-on-findings gate (read from env).
    assert "3)" in map_script
    assert "$FAIL_ON_FINDINGS" in map_script
    assert "fail-on-findings" in str(map_step["env"]["FAIL_ON_FINDINGS"])


def test_action_uses_action_path_for_comment_script():
    """External users invoke the script via the action_path prefix."""
    steps = _load("action.yml")["runs"]["steps"]
    comment_step = next(s for s in steps if s.get("name") == "Post PR comment")
    assert "github.action_path" in comment_step["run"]


def test_dogfood_workflow_parses_and_uses_local_install():
    data = _load(".github/workflows/revrem-pr.yml")
    assert data["name"] == "RevRem (dogfood)"
    job = data["jobs"]["revrem"]
    # Least privilege declared on the caller workflow.
    assert data["permissions"]["pull-requests"] == "write"
    assert data["permissions"]["contents"] == "read"
    # The uses: ./ step (local action) + install-mode local.
    revrem_step = next(
        s for s in job["steps"] if s.get("uses", "").strip() == "./"
    )
    assert revrem_step["with"]["install-mode"] == "local"
    assert revrem_step["with"]["profile"] == "dogfood"
