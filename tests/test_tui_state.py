from __future__ import annotations

import json

from code_review_loop import profiles, tui_state


def test_home_snapshot_collects_profiles_history_and_harnesses(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.pipeline]
base = "main"
max_iterations = 3
checks = ["pytest -q", "git diff --check"]
""",
        encoding="utf-8",
    )
    history_path = tmp_path / "runs.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "artifact_dir": str(tmp_path / "artifacts"),
                "artifact_paths": {"summary": str(tmp_path / "artifacts" / "summary.json")},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "summary.json").write_text("{}\n", encoding="utf-8")

    snapshot = tui_state.build_home_snapshot(
        cwd=repo,
        home=home,
        history_path=history_path,
    )

    assert snapshot.cwd == str(repo)
    assert [profile.name for profile in snapshot.profiles] == ["final-pr"]
    assert snapshot.profiles[0].checks == ("pytest -q", "git diff --check")
    assert snapshot.recent_runs[0]["run_id"] == "run-1"
    assert snapshot.run_monitors[0].run_id == "run-1"
    assert snapshot.run_monitors[0].final_status == "clear"
    assert snapshot.run_monitors[0].artifacts[0].kind == "summary"
    assert snapshot.run_monitors[0].artifacts[0].exists is True
    assert snapshot.run_previews[0].shell_command == (
        "revrem --profile final-pr --base main --max-iterations 3 "
        "--summary-format text --check 'pytest -q' --check 'git diff --check'"
    )
    assert {harness.name for harness in snapshot.harnesses} >= {
        "codex",
        "claude",
        "gemini",
        "opencode",
        "kilo",
    }
    assert next(harness for harness in snapshot.harnesses if harness.name == "codex").implemented is True
    assert next(harness for harness in snapshot.harnesses if harness.name == "claude").implemented is False


def test_home_snapshot_resolves_shared_defaults_before_building_previews(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.pipeline]
base = "trunk"
checks = ["pytest -q", "git diff --check"]

[profiles.final-pr]
description = "Final PR"
""",
        encoding="utf-8",
    )

    snapshot = tui_state.build_home_snapshot(cwd=repo, home=home)

    assert [profile.name for profile in snapshot.profiles] == ["final-pr"]
    assert snapshot.profiles[0].base == "trunk"
    assert snapshot.profiles[0].checks == ("pytest -q", "git diff --check")
    assert snapshot.run_previews[0].shell_command == (
        "revrem --profile final-pr --base trunk --max-iterations 2 "
        "--summary-format text --check 'pytest -q' --check 'git diff --check'"
    )


def test_pipeline_phases_model_review_triage_checks_and_commit():
    profile = profiles.Profile(
        name="demo",
        pipeline=profiles.PipelineConfig(checks=("pytest -q",)),
        review=profiles.PhaseConfig(model="gpt-5.5", reasoning_effort="high", timeout_seconds=600),
        triage=profiles.TriageConfig(enabled=True, model="gpt-5.4-mini", reasoning_effort="low"),
        remediation=profiles.PhaseConfig(model="gpt-5.4-mini", reasoning_effort="medium"),
        commit=profiles.CommitConfig(enabled=True, message_model="gpt-5.3-codex-spark"),
    )

    phases = tui_state.pipeline_phases(profile)

    assert [phase.name for phase in phases] == [
        "review",
        "triage",
        "remediation",
        "checks",
        "commit",
    ]
    assert phases[0].model == "gpt-5.5"
    assert phases[1].enabled is True
    assert phases[2].reasoning_effort == "medium"
    assert phases[3].command_count == 1
    assert phases[4].model == "gpt-5.3-codex-spark"


def test_pipeline_phases_preserve_disabled_optional_phase_shape():
    profile = profiles.Profile(
        name="minimal",
        pipeline=profiles.PipelineConfig(checks=()),
        triage=profiles.TriageConfig(enabled=False, model="gpt-5.3-codex-spark"),
        commit=profiles.CommitConfig(enabled=False, message_model="gpt-5.3-codex-spark"),
    )

    phases = tui_state.pipeline_phases(profile)

    assert [phase.name for phase in phases] == [
        "review",
        "triage",
        "remediation",
        "checks",
        "commit",
    ]
    assert phases[1].enabled is False
    assert phases[1].model == "gpt-5.3-codex-spark"
    assert phases[3].enabled is False
    assert phases[3].command_count == 0
    assert phases[4].enabled is False


def test_run_preview_includes_operator_visible_profile_options():
    profile = profiles.Profile(
        name="showcase",
        pipeline=profiles.PipelineConfig(
            base="trunk",
            max_iterations=5,
            checks=("pytest -q",),
        ),
        commit=profiles.CommitConfig(enabled=True),
        output=profiles.OutputConfig(
            summary_format="both",
            progress_style="rich",
            debug_status_detection=True,
            terminal_title=True,
        ),
    )

    preview = tui_state.run_preview(profile)

    assert preview.argv == (
        "revrem",
        "--profile",
        "showcase",
        "--base",
        "trunk",
        "--max-iterations",
        "5",
        "--summary-format",
        "both",
        "--progress-style",
        "rich",
        "--debug-status-detection",
        "--terminal-title",
        "--commit-after-remediation",
        "--check",
        "pytest -q",
    )
    assert preview.shell_command.endswith("--check 'pytest -q'")


def test_launch_plan_adds_dry_run_without_mutating_profile_preview():
    profile = profiles.Profile(name="demo")

    preview = tui_state.run_preview(profile)
    plan = tui_state.launch_plan(profile, dry_run=True)

    assert preview.argv[-1] == "text"
    assert plan.mode == "dry-run"
    assert plan.argv[-1] == "--dry-run"
    assert plan.shell_command == "revrem --profile demo --base main --max-iterations 2 --summary-format text --dry-run"


def test_run_monitor_view_flattens_summary_artifacts():
    summary_path = "tmp/code-review-loop/run/summary.json"
    record = {
        "run_id": "abc",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "artifact_dir": "tmp/code-review-loop/run",
        "artifact_paths": {
            "summary": summary_path,
            "reviews": ["tmp/code-review-loop/run/review-1.txt"],
        },
    }

    monitor = tui_state.run_monitor_view(record)

    assert monitor.run_id == "abc"
    assert monitor.final_status == "findings"
    assert monitor.stopped_reason == "max_iterations_reached"
    assert [artifact.kind for artifact in monitor.artifacts] == ["summary", "reviews"]
    assert monitor.artifacts[0].path == summary_path
