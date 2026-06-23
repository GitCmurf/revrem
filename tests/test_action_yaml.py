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
        "checks",
        "routing",
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


def test_action_warns_that_github_ci_makes_paid_provider_calls():
    data = _load("action.yml")
    description = data["description"].lower()
    assert "paid model api calls" in description
    assert "max-usd" in description
    assert "max-tokens" in description
    max_usd = data["inputs"]["max-usd"]["description"].lower()
    assert "real api charges" in max_usd
    assert "github ci" in max_usd


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
    run_dir_line = next(line for line in script.splitlines() if "RUN_DIR=" in line)
    assert ".revrem/runs" not in run_dir_line
    assert "diagnostics.json" in script


def test_action_diagnostics_fallback_is_portable():
    """The setup-crash diagnostics fallback must not rely on GNU find flags.

    macOS/BSD find does not support ``-printf``; suppressing that error leaves
    DIAGNOSTICS empty and hides the root cause on macOS runners.
    """
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    script = run_step["run"]
    assert "Path(\".revrem/runs\").rglob(\"diagnostics.json\")" in script
    assert "-printf" not in script


def test_action_scratch_files_live_under_runner_temp():
    """Action-owned stdout/stderr/report files must not be created in the checkout.

    The dogfood profile can require a clean worktree before provider calls, so
    files like revrem-out.json in the repository root break the live gate.
    """
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    render_step = next(s for s in steps if s.get("name") == "Render report")
    upload_step = next(s for s in steps if s.get("name") == "Upload report artifact")
    map_step = next(s for s in steps if s.get("name") == "Map exit code")

    assert "RUNNER_TEMP" in run_step["run"]
    assert "> \"$REVREM_STDOUT\"" in run_step["run"]
    assert "2> \"$REVREM_STDERR\"" in run_step["run"]
    assert "revrem-out.json" not in render_step["run"]
    assert "revrem-report.html" not in str(upload_step["with"]["path"])
    assert "$REVREM_STDERR" in map_step["run"]


def test_action_splits_checks_safely():
    """checks input is split into repeated --check flags, never interpolated as one string."""
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    script = run_step["run"]
    assert "while IFS=" in script
    assert '--check "$line"' in script


def test_action_run_step_fails_fast_with_errexit():
    """The Run revrem step's setup region must run under `set -e`.

    Without errexit a failed `mkdir -p "$ACTION_TMP"` (or a failed `$GITHUB_ENV`
    export) is silently ignored, so the path exports are skipped and downstream
    steps receive empty REVREM_* paths. The revrem invocation itself is
    deliberately bracketed with `set +e` ... `set -e` to capture its non-zero
    exit code, so that toggle must remain after the fix.
    """
    steps = _load("action.yml")["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    script = run_step["run"]
    assert "set -euo pipefail" in script  # fail-fast over the setup region
    assert "set -uo pipefail" not in script  # not the errexit-less variant
    assert "set +e" in script  # revrem call still brackets errexit to read $?


def test_action_maps_documented_error_exit_code_explicitly():
    """Exit code 1 is a typed RevRem error, not an unexpected process shape."""
    steps = _load("action.yml")["runs"]["steps"]
    map_step = next(s for s in steps if s.get("name") == "Map exit code")
    script = map_step["run"]
    assert "1)" in script
    assert "RevRem ended with an error" in script
    unexpected_index = script.index("unexpected code")
    error_index = script.index("RevRem ended with an error")
    assert error_index < unexpected_index


def test_action_error_annotation_includes_report_failure_summary():
    steps = _load("action.yml")["runs"]["steps"]
    map_step = next(s for s in steps if s.get("name") == "Map exit code")
    script = map_step["run"]
    assert "REVREM_REPORT_JSON" in script
    assert "failure_summary" in script
    assert "RevRem ended with an error: $DETAIL" in script


def test_action_routing_input_is_validated_and_env_mapped():
    """The action can disable profile routing for Codex-only CI dogfood runs."""
    data = _load("action.yml")
    assert data["inputs"]["routing"]["default"] == ""
    steps = data["runs"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run revrem")
    assert run_step["env"]["ROUTING"] == "${{ inputs.routing }}"
    script = run_step["run"]
    assert "Input 'routing' must be 'true', 'false', or empty" in script
    assert "ARGS+=(--routing)" in script
    assert "ARGS+=(--no-routing)" in script


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


def test_action_run_scripts_contain_no_expression_delimiters():
    """GitHub template-parses composite run scripts before bash sees them.

    Even expression-looking text in comments can make the action manifest fail
    to load, so run scripts must read expressions through env/with fields only.
    """
    steps = _load("action.yml")["runs"]["steps"]
    offenders = [
        s.get("name")
        for s in steps
        if isinstance(s.get("run"), str) and "${{" in s["run"]
    ]
    assert not offenders, f"steps include expression text in run scripts: {offenders}"


def test_action_input_descriptions_do_not_contain_expression_text():
    """Action metadata descriptions are parsed as templates by the runner.

    Do not include `${{ ... }}` examples in descriptions; they can fail action
    loading before any step executes.
    """
    inputs = _load("action.yml")["inputs"]
    offenders = [
        name
        for name, spec in inputs.items()
        if "${{" in str(spec.get("description", ""))
    ]
    assert not offenders, f"input descriptions contain expression text: {offenders}"


def test_action_wires_github_token_via_input():
    """The comment step receives the token from the github-token input, not an
    unset env var (P0-3). Composite actions can't read secrets, so the caller
    passes github.token in (or omits it and the step falls back)."""
    data = _load("action.yml")
    assert "github-token" in data["inputs"]
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


def test_action_github_token_default_is_empty_not_an_expression():
    """The github-token default must be empty (not ${{ github.token }}): a
    non-empty literal default is truthy and would defeat the comment step's
    `inputs.github-token || github.token` fallback, sending a bad token if the
    expression is not evaluated in the default (GPT re-review of c14-c17)."""
    data = _load("action.yml")
    default = data["inputs"]["github-token"].get("default", "")
    assert default == "", f"github-token default must be empty; got {default!r}"


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
    assert "github.action_path" in str(comment_step["env"]["ACTION_PATH"])
    assert "$ACTION_PATH/scripts/ci/post_pr_comment.py" in comment_step["run"]


def test_dogfood_workflow_parses_and_uses_local_install():
    data = _load(".github/workflows/revrem-pr.yml")
    assert data["name"] == "RevRem (dogfood)"
    job = data["jobs"]["revrem"]
    assert job["if"] == "github.event.pull_request.head.repo.fork == false"
    assert job["timeout-minutes"] == 20
    # Least privilege declared on the caller workflow.
    assert data["permissions"]["pull-requests"] == "write"
    assert data["permissions"]["contents"] == "read"
    dependency_step = next(
        s for s in job["steps"] if s.get("name") == "Install dogfood dependencies"
    )
    dependency_script = dependency_step["run"]
    assert "python -m venv .venv" in dependency_script
    assert 'pip install -e ".[dev]"' in dependency_script
    assert "meminit @ git+https://github.com/GitCmurf/meminit.git@" in dependency_script
    codex_step = next(
        s for s in job["steps"] if s.get("uses", "").strip() == "openai/codex-action@v1"
    )
    assert codex_step["name"] == "Start Codex proxy"
    assert codex_step["with"]["openai-api-key"] == "${{ secrets.CODEX_API_KEY }}"
    git_step = next(
        s for s in job["steps"] if s.get("name") == "Configure git author"
    )
    assert 'git config user.name "RevRem Action"' in git_step["run"]
    assert (
        'git config user.email "revrem-action@users.noreply.github.com"'
        in git_step["run"]
    )
    # The uses: ./ step (local action) + install-mode local.
    revrem_step = next(
        s for s in job["steps"] if s.get("uses", "").strip() == "./"
    )
    assert revrem_step["with"]["install-mode"] == "local"
    assert revrem_step["with"]["profile"] == "dogfood"
    assert revrem_step["with"]["routing"] == "false"
    assert revrem_step["with"]["max-wall-seconds"] == "900"
    assert revrem_step["with"]["max-usd"] == "1.00"
    checks = revrem_step["with"]["checks"]
    for command in (
        "./.venv/bin/ruff check .",
        "./.venv/bin/mypy src",
        "./.venv/bin/lint-imports",
        "./.venv/bin/meminit check --format json",
        "./.venv/bin/pytest -q",
        "git diff --check",
    ):
        assert command in checks
