from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from code_review_loop import harnesses, profiles, tui_run_controller, tui_state
from code_review_loop.tui_loop_model import LoopEditModel
from tests.support.git_fixtures import init_repo
from tests.support.run_artifact_compare import assert_equivalent_run_artifacts


@pytest.mark.parametrize(
    ("scenario_name", "profile_toml", "expected_code"),
    [
        (
            "clear",
            """
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
review.harness = "fake"
review.model = "review_clear"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
""",
            0,
        ),
        (
            "findings",
            """
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = true
review.harness = "fake"
review.model = "review_findings"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
""",
            2,
        ),
        (
            "unknown",
            """
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
review.harness = "fake"
review.model = "unknown"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
""",
            2,
        ),
        (
            "review-failure",
            """
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
review.harness = "fake"
review.model = "unsupported"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
""",
            1,
        ),
        (
            "setup-failure",
            """
[profiles.equivalence]
pipeline.base = "missing-base"
pipeline.max_iterations = 1
pipeline.final_review = false
review.harness = "fake"
review.model = "review_clear"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
""",
            4,
        ),
        (
            "check-failure",
            f"""
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
pipeline.checks = ["{sys.executable} check_fail.py"]
review.harness = "fake"
review.model = "review_findings"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
""",
            2,
        ),
        (
            "cost-ceiling",
            """
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
review.harness = "fake"
review.model = "cost_ceiling"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
budgets.max_tokens = 5
""",
            3,
        ),
    ],
)
def test_tui_live_run_matches_cli_artifacts(
    tmp_path, monkeypatch, scenario_name, profile_toml, expected_code
):
    repo = _init_repo(tmp_path / scenario_name / "repo", profile_toml)
    home = tmp_path / scenario_name / "home"
    home.mkdir()
    fixture_dir = _fixture_dir(tmp_path / scenario_name / "fixtures")
    cli_dir = tmp_path / scenario_name / "runs" / "cli"
    tui_dir = tmp_path / scenario_name / "runs" / "tui"
    env = {
        **os.environ,
        "HOME": str(home),
        harnesses.FAKE_HARNESS_ENV: "1",
        harnesses.FAKE_HARNESS_FIXTURE_ENV: str(fixture_dir),
    }
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    monkeypatch.setenv(harnesses.FAKE_HARNESS_FIXTURE_ENV, str(fixture_dir))
    monkeypatch.setenv("HOME", str(home))

    cli_result = _run_cli(repo=repo, artifact_dir=cli_dir, env=env)
    tui_status, tui_exit_code = _run_tui_controller(repo=repo, artifact_dir=tui_dir)

    assert cli_result.returncode == expected_code, cli_result.stderr + cli_result.stdout
    assert tui_exit_code == expected_code
    assert tui_status == tui_run_controller.classify_exit(
        expected_code,
        summary=_read_summary(tui_dir),
    )
    assert_equivalent_run_artifacts(cli_dir, tui_dir)


def test_loop_save_keeps_launch_plan_cli_equivalent(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
        "[profiles.edit.review]\nmodel='gpt-5.5'\n",
        encoding="utf-8",
    )
    model = LoopEditModel.load("edit", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.save()
    profile = profiles.resolve_profile("edit", cwd=repo, require_implemented=False)
    plan = tui_state.launch_plan(profile, dry_run=False)
    assert plan.argv == ("revrem", "--profile", "edit")


def test_loop_save_run_artifacts_match_cli_set_run(tmp_path, monkeypatch):
    profile_toml = """
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
review.harness = "fake"
review.model = "unsupported"
remediation.harness = "fake"
remediation.model = "remediation"
triage.enabled = false
"""
    repo_model = _init_repo(tmp_path / "via_model" / "repo", profile_toml)
    repo_cli = _init_repo(tmp_path / "via_cli" / "repo", profile_toml)
    home = tmp_path / "home"
    home.mkdir()
    fixture_dir = _fixture_dir(tmp_path / "fixtures")
    env = {
        **os.environ,
        "HOME": str(home),
        harnesses.FAKE_HARNESS_ENV: "1",
        harnesses.FAKE_HARNESS_FIXTURE_ENV: str(fixture_dir),
    }
    monkeypatch.setenv(harnesses.FAKE_HARNESS_ENV, "1")
    monkeypatch.setenv(harnesses.FAKE_HARNESS_FIXTURE_ENV, str(fixture_dir))
    monkeypatch.setenv("HOME", str(home))

    model = LoopEditModel.load("equivalence", cwd=repo_model)
    model.set_field("review.model", "review_clear")
    model.save()
    profiles.set_profile_field("equivalence", "review.model", "review_clear", cwd=repo_cli)

    model_result = _run_cli(repo_model, tmp_path / "runs" / "model", env)
    cli_result = _run_cli(repo_cli, tmp_path / "runs" / "cli", env)

    assert model_result.returncode == 0, model_result.stderr + model_result.stdout
    assert cli_result.returncode == 0, cli_result.stderr + cli_result.stdout
    assert_equivalent_run_artifacts(tmp_path / "runs" / "model", tmp_path / "runs" / "cli")


def _init_repo(repo: Path, profile_toml: str) -> Path:
    # Portable failing check used by the check-failure scenario: a committed
    # script avoids embedding shell-style quoting inside the profile TOML.
    return init_repo(
        repo,
        extra_files={
            ".revrem.toml": profile_toml,
            "check_fail.py": "import sys\n\nsys.exit(1)\n",
        },
    )


def _fixture_dir(path: Path) -> Path:
    source = Path(__file__).resolve().parent / "fixtures" / "harnesses"
    shutil.copytree(source, path)
    unknown_dir = path / "unknown"
    unknown_dir.mkdir()
    (unknown_dir / "review.txt").write_text(
        "The fake reviewer did not emit a recognized status marker.\n",
        encoding="utf-8",
    )
    return path


def _run_cli(repo: Path, artifact_dir: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "code_review_loop",
            "--profile",
            "equivalence",
            "--artifact-dir",
            str(artifact_dir),
            "--no-tty",
            "--pending-review",
            "ignore",
            "--summary-format",
            "json",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_tui_controller(
    repo: Path,
    artifact_dir: Path,
) -> tuple[tui_run_controller.RunControllerStatus, int | None]:
    profile = profiles.resolve_profile("equivalence", cwd=repo)
    profile = replace(profile, output=replace(profile.output, artifact_dir=str(artifact_dir)))
    plan = tui_state.launch_plan(profile, dry_run=False)
    controller = tui_run_controller.LiveRunController()
    controller.start(
        profile=profile,
        plan=plan,
        cwd=repo,
        entrypoint_resolver=lambda argv: [sys.executable, "-m", "code_review_loop", *argv[1:]],
    )
    assert controller.process is not None
    deadline = time.monotonic() + 30
    while controller.process.poll() is None:
        if time.monotonic() > deadline:
            controller.cancel(grace_seconds=0.1)
            raise AssertionError(f"TUI controller run timed out for {artifact_dir}")
        time.sleep(0.01)
    status = controller.finish(controller.process.returncode)
    return status, controller.exit_code


def _read_summary(run_dir: Path) -> dict[str, object]:
    payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload
