from __future__ import annotations

import io
import json
import os
import subprocess
from importlib import import_module

from code_review_loop import application as application_mod
from code_review_loop import profiles
from code_review_loop.core.outcome import OutcomeClear

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


def _clear_result(summary: dict[str, object]) -> application_mod.ReviewLoopResult:
    return application_mod.ReviewLoopResult(
        summary=summary, outcome=OutcomeClear(reason="review_clear")
    )


def _write_pending_review(
    root,
    text="Full review comments:\n\n- [P2] Fix pending review\n",
    *,
    git_state=None,
):
    run = root / ".revrem" / "runs" / "20260428T010000Z"
    run.mkdir(parents=True)
    review = run / "review-1.txt"
    review.write_text(text, encoding="utf-8")
    summary = {
        "final_status": "error",
        "stopped_reason": "triage_failed",
        "artifact_paths": {"reviews": [str(review)]},
    }
    if git_state is not None:
        summary["git_state"] = git_state
    (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return review


def test_main_pending_review_auto_uses_candidate(tmp_path, monkeypatch):
    pending_review = _write_pending_review(tmp_path)
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--pending-review", "auto", "--quiet-progress"])

    assert exit_code == 0
    assert captured_configs[0].initial_review_file == pending_review


def test_main_pending_review_does_not_override_explicit_initial_review(
    tmp_path,
    monkeypatch,
):
    pending_review = _write_pending_review(tmp_path)
    explicit_review = tmp_path / "explicit-review.txt"
    explicit_review.write_text("explicit", encoding="utf-8")
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--initial-review-file",
            str(explicit_review),
            "--pending-review",
            "auto",
            "--quiet-progress",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].initial_review_file == explicit_review
    assert captured_configs[0].initial_review_file != pending_review


def test_main_pending_review_default_ignores_candidate_when_not_tty(
    tmp_path,
    monkeypatch,
):
    _write_pending_review(tmp_path)
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--quiet-progress"])

    assert exit_code == 0
    assert captured_configs[0].initial_review_file is None


def test_main_pending_review_prompt_can_start_fresh(tmp_path, monkeypatch):
    _write_pending_review(tmp_path)
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)
    monkeypatch.setattr("sys.stdin", _TTYStringIO("f\n"))
    monkeypatch.setattr("sys.stdout", _TTYStringIO())

    exit_code = cli_main.main(["--quiet-progress"])

    assert exit_code == 0
    assert captured_configs[0].initial_review_file is None


def test_main_pending_review_prompt_can_show_details_then_use(
    tmp_path,
    monkeypatch,
    capsys,
):
    pending_review = _write_pending_review(tmp_path)
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)
    monkeypatch.setattr("sys.stdin", _TTYStringIO("d\nu\n"))
    monkeypatch.setattr("sys.stdout", _TTYStringIO())

    exit_code = cli_main.main(["--quiet-progress"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured_configs[0].initial_review_file == pending_review
    assert "Pending review detail:" in captured.err
    assert "Fix pending review" in captured.err


def test_main_pending_review_prompt_can_use_incompatible_candidate(
    tmp_path,
    monkeypatch,
    capsys,
):
    pending_review = _write_pending_review(
        tmp_path,
        git_state={
            "available": True,
            "head": "old-head",
            "base": "main",
            "base_commit": "base-sha",
            "merge_base": "base-sha",
        },
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)
    monkeypatch.setattr(
        cli_main,
        "current_git_state_for_latest",
        lambda cwd, base: {
            "available": True,
            "head": "new-head",
            "base": "main",
            "base_commit": "base-sha",
            "merge_base": "base-sha",
        },
    )
    monkeypatch.setattr("sys.stdin", _TTYStringIO("u\n"))
    monkeypatch.setattr("sys.stdout", _TTYStringIO())

    exit_code = cli_main.main(["--quiet-progress"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured_configs[0].initial_review_file == pending_review
    assert captured_configs[0].initial_review_mode == "stale"
    assert "different HEAD/base" in captured.err
    assert "Validate this older review?" in captured.err


def test_main_pending_review_prompt_can_cancel_before_provider_calls(
    tmp_path,
    monkeypatch,
):
    _write_pending_review(tmp_path)

    def fail_run_loop(config):
        raise AssertionError("run loop should not start after cancel")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)
    monkeypatch.setattr("sys.stdin", _TTYStringIO("c\n"))
    monkeypatch.setattr("sys.stdout", _TTYStringIO())

    assert cli_main.main(["--quiet-progress"]) == 130


def test_main_auto_commit_refuses_dirty_worktree_before_provider_calls(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_run_loop(config):
        raise AssertionError("run loop should not start from a dirty auto-commit worktree")

    def fake_git_status(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout=" M src/code_review_loop/cli/main.py\n?? local-note.txt\n",
            stderr="",
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)
    monkeypatch.setattr(cli_main.subprocess, "run", fake_git_status)

    exit_code = cli_main.main(["--commit-after-remediation", "--quiet-progress"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "auto-commit requires a clean worktree" in captured.err
    assert "src/code_review_loop/cli/main.py" in captured.err
    assert "local-note.txt" in captured.err


def test_main_auto_commit_refuses_dirty_worktree_from_subdirectory(
    tmp_path,
    monkeypatch,
    capsys,
):
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    monkeypatch.chdir(subdir)

    def fail_run_loop(config):
        raise AssertionError("run loop should not start from a dirty auto-commit worktree")

    def fake_git_status(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout=" M src/code_review_loop/cli/main.py\n?? local-note.txt\n",
            stderr="",
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)
    monkeypatch.setattr(cli_main.subprocess, "run", fake_git_status)

    exit_code = cli_main.main(["--commit-after-remediation", "--quiet-progress"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "auto-commit requires a clean worktree" in captured.err
    assert "local-note.txt" in captured.err


def test_main_auto_commit_preflight_ignores_artifact_status_lines(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    def fake_git_status(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout="?? .revrem/runs/20260606T000000Z/review-1.txt\n",
            stderr="",
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)
    monkeypatch.setattr(cli_main.subprocess, "run", fake_git_status)

    exit_code = cli_main.main(["--commit-after-remediation", "--quiet-progress"])

    assert exit_code == 0
    assert captured_configs


def test_main_resolves_latest_initial_review_from_custom_artifact_dir(tmp_path, monkeypatch):
    custom_root = tmp_path / "custom-artifacts"
    custom_run = custom_root / "20260428T010000Z"
    default_run = tmp_path / "tmp" / "code-review-loop" / "20260428T020000Z"
    custom_run.mkdir(parents=True)
    default_run.mkdir(parents=True)
    custom_review = custom_run / "review-final.txt"
    default_review = default_run / "review-final.txt"
    custom_review.write_text("custom", encoding="utf-8")
    default_review.write_text("default", encoding="utf-8")
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--initial-review-file",
            "latest",
            "--artifact-dir",
            str(custom_root),
            "--quiet-progress",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].artifact_dir == custom_root
    assert captured_configs[0].initial_review_file == custom_review
    assert captured_configs[0].initial_review_file != default_review


def test_main_save_profile_writes_project_config_and_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text("[defaults.pipeline]\nfinal_review = false\n", encoding="utf-8")

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--base",
            "trunk",
            "--max-iterations",
            "7",
            "--final-review",
            "--review-model",
            "gpt-5.5",
            "--remediation-model",
            "gpt-5.4-mini",
            "--reasoning-effort",
            "medium",
            "--timeout-seconds",
            "1800",
            "--summary-format",
            "text",
            "--debug-status-detection",
            "--terminal-title",
            "--check",
            "pytest -q",
            "--check",
            "git diff --check",
            "--progress-style",
            "rich",
            "--commit-after-remediation",
            "--commit-message-model",
            "gpt-5.3-codex-spark",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    project_config = profiles.project_config_path(tmp_path)
    saved = project_config.read_text(encoding="utf-8")
    assert "[profiles.final-pr]" in saved
    assert 'base = "trunk"' in saved
    assert "max_iterations = 7" in saved
    assert '"pytest -q"' in saved
    assert '"git diff --check"' in saved
    assert 'model = "gpt-5.5"' in saved
    assert "final_review = true" in saved
    assert 'progress_style = "rich"' in saved
    assert "terminal_title = true" in saved
    assert "enabled = true" in saved


def test_main_save_profile_preserves_disabled_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--timeout-seconds",
            "0",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    saved = profiles.project_config_path(tmp_path).read_text(encoding="utf-8")
    assert saved.count("timeout_seconds = 0") == 3


def test_main_save_profile_round_trips_explicit_review_and_check_timeouts(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--timeout-seconds",
            "600",
            "--review-timeout-seconds",
            "0",
            "--check-timeout-seconds",
            "30",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    saved = profiles.resolve_profile("final-pr", cwd=tmp_path)
    assert saved.review.timeout_seconds == 0
    assert saved.pipeline.check_timeout_seconds == 30


def test_main_save_profile_preserves_external_review_truncation_policy(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--external-review-truncation-policy",
            "fail",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    saved = profiles.project_config_path(tmp_path).read_text(encoding="utf-8")
    assert 'external_review_truncation_policy = "fail"' in saved


def test_main_save_profile_preserves_routing_and_harness_overrides(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text(
        """
[profiles.routed.triage]
enabled = true
contract = "v2"

[profiles.routed.triage.routing]
enabled = true
default_route = "frontier"

[[profiles.routed.triage.routing.rule]]
id = "security"
[profiles.routed.triage.routing.rule.when]
domain_tags_any = ["security"]
[profiles.routed.triage.routing.rule.then]
route = "frontier"

[profiles.routed.triage.routes.midtier]
harness = "codex"
model = "gpt-5.3-codex"

[profiles.routed.triage.routes.frontier]
harness = "claude"
model = "claude-opus"
fallback = "midtier"
""",
        encoding="utf-8",
    )

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(application_mod, "run_review_loop", fail_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "routed",
            "--harness-bin",
            "claude=/opt/claude/bin/claude",
            "--save-profile",
            "saved-routed",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved saved-routed in" in captured.out

    saved = profiles.resolve_profile("saved-routed", cwd=tmp_path)
    assert saved.triage.contract == "v2"
    assert saved.triage.routing.enabled is True
    assert saved.triage.routing.default_route == "frontier"
    assert saved.triage.routing.rule[0].id == "security"
    assert saved.triage.routing.rule[0].then.route == "frontier"
    assert saved.triage.routes["frontier"].harness == "claude"
    assert saved.triage.routes["frontier"].fallback == "midtier"
    assert saved.runtime.harness_executables == {
        "claude": "/opt/claude/bin/claude",
    }


def test_main_save_profile_is_non_destructive_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text('[profiles.final-pr]\ndescription = "Keep me"\n', encoding="utf-8")

    exit_code = cli_main.main(["--save-profile", "final-pr"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "profile already exists: final-pr" in captured.err
    assert "Keep me" in project_config.read_text(encoding="utf-8")


def test_main_resolves_latest_initial_review_from_profile_artifact_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    custom_root = tmp_path / "custom-artifacts"
    custom_run = custom_root / "20260428T010000Z"
    sibling_root = tmp_path / "other-artifacts"
    sibling_run = sibling_root / "20260428T020000Z"
    custom_run.mkdir(parents=True)
    sibling_run.mkdir(parents=True)

    custom_review = custom_run / "review-final.txt"
    sibling_review = sibling_run / "review-final.txt"
    custom_review.write_text("custom", encoding="utf-8")
    sibling_review.write_text("sibling", encoding="utf-8")
    os.utime(custom_review, (1_000_000, 1_000_000))
    os.utime(sibling_review, (2_000_000, 2_000_000))

    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"""
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.output]
artifact_dir = "{custom_root}"
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(
        [
            "--profile",
            "final-pr",
            "--initial-review-file",
            "latest",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].artifact_dir == custom_root
    assert captured_configs[0].initial_review_file == custom_review
    assert captured_configs[0].initial_review_file != sibling_review


def test_main_uses_profile_defaults_and_cli_overrides(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.pipeline]
base = "trunk"
max_iterations = 3
checks = ["pytest -q", "git diff --check"]

[profiles.final-pr.review]
model = "gpt-5.5"
reasoning_effort = "medium"
timeout_seconds = 1800

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"
reasoning_effort = "low"

[profiles.final-pr.commit]
enabled = true
message_model = "gpt-5.3-codex-spark"

[profiles.final-pr.output]
summary_format = "json"
debug_status_detection = true
quiet_progress = true

[profiles.final-pr.budgets]
max_wall_seconds = 120
max_tokens = 1000
max_usd = "0.75"
soft_warn_fraction = 0.5
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return _clear_result(
            {
                "artifact_dir": str(config.artifact_dir),
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "iterations": [],
            }
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--profile", "final-pr", "--base", "main", "--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.base == "main"
    assert config.max_iterations == 3
    assert config.review_model == "gpt-5.5"
    assert config.remediation_model == "gpt-5.4-mini"
    assert config.reasoning_effort is None
    assert config.review_reasoning_effort == "medium"
    assert config.remediation_reasoning_effort == "low"
    assert config.commit_after_remediation is True
    assert config.commit_message_model == "gpt-5.3-codex-spark"
    assert config.timeout_seconds == 300
    assert config.check_commands == ("pytest -q", "git diff --check")
    assert config.debug_status_detection is True
    assert config.progress is False
    assert config.budget_config.max_wall_seconds == 120
    assert config.budget_config.max_tokens == 1000
    assert str(config.budget_config.max_usd) == "0.75"
    assert config.budget_config.soft_warn_fraction == 0.5
