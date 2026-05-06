from __future__ import annotations

import json

import pytest

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
    assert snapshot.run_previews[0].shell_command == "revrem --profile final-pr"
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
    assert snapshot.run_previews[0].shell_command == "revrem --profile final-pr"


def test_shell_model_reuses_batch_resolved_profiles(tmp_path, monkeypatch):
    profile = profiles.Profile(
        name="final-pr",
        description="Final PR",
        pipeline=profiles.PipelineConfig(base="trunk", checks=("git diff --check",)),
    )
    calls = []

    def fake_resolve_profiles(*, cwd, home=None, require_implemented=True):
        calls.append((cwd, home, require_implemented))
        return [profile]

    def fail_resolve_profile(*args, **kwargs):
        raise AssertionError("build_shell_model should not re-read a selected profile")

    monkeypatch.setattr(tui_state.profiles, "resolve_profiles", fake_resolve_profiles)
    monkeypatch.setattr(tui_state.profiles, "resolve_profile", fail_resolve_profile)

    model = tui_state.build_shell_model(cwd=tmp_path, selected_profile_name="final-pr")

    assert calls == [(tmp_path, None, False)]
    assert model.selected_profile_name == "final-pr"
    assert model.selected_launch_plan is not None
    assert model.selected_launch_plan.shell_command == "revrem --profile final-pr --dry-run"
    assert model.snapshot.profiles[0].base == "trunk"


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


def test_run_preview_keeps_profile_command_minimal_to_avoid_drift():
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
    )
    assert preview.shell_command == "revrem --profile showcase"
    assert preview.checks == ("pytest -q",)


def test_launch_plan_adds_dry_run_without_mutating_profile_preview():
    profile = profiles.Profile(name="demo")

    preview = tui_state.run_preview(profile)
    plan = tui_state.launch_plan(profile, dry_run=True)

    assert preview.argv[-1] == "demo"
    assert plan.mode == "dry-run"
    assert plan.argv[-1] == "--dry-run"
    assert plan.shell_command == "revrem --profile demo --dry-run"


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


def test_run_monitor_view_resolves_relative_artifacts_against_record_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    other_repo = tmp_path / "other-repo"
    repo.mkdir()
    other_repo.mkdir()
    (repo / ".git").mkdir()
    history_path = tmp_path / "runs.jsonl"
    artifact_path = repo / "tmp" / "code-review-loop" / "run" / "summary.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("{}\n", encoding="utf-8")
    history_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "cwd": str(repo),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "artifact_dir": "tmp/code-review-loop/run",
                "artifact_paths": {"summary": "tmp/code-review-loop/run/summary.json"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(other_repo)

    snapshot = tui_state.build_home_snapshot(
        cwd=other_repo,
        home=home,
        history_path=history_path,
    )

    assert snapshot.run_monitors[0].artifacts[0].path == "tmp/code-review-loop/run/summary.json"
    assert snapshot.run_monitors[0].artifacts[0].exists is True


def test_shell_model_builds_operator_screens_and_selected_launch_plan(tmp_path):
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
checks = ["git diff --check"]

[profiles.final-pr.triage]
enabled = true
model = "gpt-5.3-codex-spark"
reasoning_effort = "low"
""",
        encoding="utf-8",
    )

    model = tui_state.build_shell_model(
        cwd=repo,
        home=home,
        selected_profile_name="final-pr",
    )

    assert [screen.name for screen in model.screens] == [
        "home",
        "profiles",
        "pipeline",
        "run-monitor",
        "actions",
    ]
    assert model.selected_profile_name == "final-pr"
    assert model.selected_launch_plan is not None
    assert model.selected_launch_plan.argv[-1] == "--dry-run"
    rendered = tui_state.render_shell_text(model)
    assert "Selected profile: final-pr" in rendered
    assert "triage: enabled" in rendered
    assert "Dry-run launch: revrem --profile final-pr --dry-run" in rendered
    assert "New, Edit, Clone, Delete, Export, and Import" in rendered


def test_profile_lifecycle_launch_plans_are_cli_backed():
    assert tui_state.show_plan_for_name("final-pr").argv == ("revrem", "config", "show", "final-pr")
    assert tui_state.new_plan_for_name("smoke").argv == ("revrem", "config", "new", "smoke")
    assert tui_state.clone_plan_for_name("final-pr", "copy").argv == (
        "revrem",
        "config",
        "clone",
        "final-pr",
        "copy",
    )
    assert tui_state.delete_plan_for_name("copy").argv == (
        "revrem",
        "config",
        "delete",
        "copy",
        "--yes",
    )
    assert tui_state.export_plan_for_name("copy").argv == ("revrem", "config", "export", "copy")
    assert tui_state.import_plan_for_path("profiles.toml").argv == (
        "revrem",
        "config",
        "import",
        "profiles.toml",
    )


def test_shell_render_escapes_dynamic_markup_in_profile_paths(tmp_path):
    profile_path = tmp_path / "home" / ".config" / "revrem" / "profiles.toml"
    snapshot = tui_state.HomeSnapshot(
        cwd=str(tmp_path),
        profiles=(
            tui_state.ProfileView(
                name="final-pr",
                description="Full PR",
                source=str(profile_path),
                base="main",
                max_iterations=2,
                checks=(),
            ),
        ),
        recent_runs=(),
        harnesses=(),
        run_previews=(),
        run_monitors=(),
    )
    model = tui_state.TuiShellModel(
        snapshot=snapshot,
        selected_profile_name="final-pr",
        selected_launch_plan=None,
        screens=(tui_state.profiles_screen(snapshot),),
    )

    rendered = tui_state.render_shell_text(model)

    assert "[b]Profiles[/b]" in rendered
    assert str(profile_path) in rendered
    assert "[profiles.toml]" not in rendered


def test_shell_model_handles_missing_profiles_without_launch_plan(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    model = tui_state.build_shell_model(cwd=repo, home=tmp_path / "home")

    assert model.selected_profile_name is None
    assert model.selected_launch_plan is None
    assert "No profiles found" in tui_state.render_shell_text(model)


def test_shell_model_rejects_unknown_selected_profile(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[profiles.final-pr]\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="profile not found: missing"):
        tui_state.build_shell_model(
            cwd=repo,
            home=home,
            selected_profile_name="missing",
        )
