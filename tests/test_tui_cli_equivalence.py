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
            "check-failure",
            f"""
[profiles.equivalence]
pipeline.max_iterations = 1
pipeline.final_review = false
pipeline.checks = ["{sys.executable} -c 'import sys; sys.exit(1)'"]
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


def _init_repo(repo: Path, profile_toml: str) -> Path:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (repo / ".revrem.toml").write_text(profile_toml, encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md", ".revrem.toml"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo


def _fixture_dir(path: Path) -> Path:
    source = Path("tests/fixtures/harnesses")
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
