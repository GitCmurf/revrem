from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest

import code_review_loop.runner as runner_mod
from code_review_loop import profiles
from code_review_loop.core.ports import RunContext
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs

cli_main = import_module("code_review_loop.cli.main")


def make_run_context(runner) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )


def run_git(cwd: Path, *args: str) -> None:
    result = runner_mod.subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=runner_mod.subprocess.PIPE,
        stderr=runner_mod.subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_review_base_preflight_reports_unrelated_local_base_and_origin_hint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "local-main.txt").write_text("local main\n", encoding="utf-8")
    run_git(repo, "add", "local-main.txt")
    run_git(repo, "commit", "-m", "local main")
    run_git(repo, "checkout", "--orphan", "public-launch")
    run_git(repo, "rm", "-rf", ".")
    (repo / "launch.txt").write_text("launch\n", encoding="utf-8")
    run_git(repo, "add", "launch.txt")
    run_git(repo, "commit", "-m", "public launch")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=repo,
        artifact_dir=repo / "artifacts",
    )

    error = runner_mod.review_base_preflight_error(config)

    assert error is not None
    assert "HEAD and base 'main' do not share a merge base" in error
    assert "Retry with --base origin/main" in error


def test_run_codex_review_fails_fast_when_base_has_no_merge_base(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    run_git(repo, "add", "main.txt")
    run_git(repo, "commit", "-m", "main")
    run_git(repo, "checkout", "--orphan", "feature")
    run_git(repo, "rm", "-rf", ".")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")

    def runner(*_args, **_kwargs):
        raise AssertionError("codex review should not run when base preflight fails")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=repo,
        artifact_dir=repo / "artifacts",
    )

    with pytest.raises(RuntimeError, match="codex review failed for review-1"):
        runner_mod.run_codex_review(config, runner, "review-1", display_label="1", ctx=make_run_context(runner))

    artifact_text = (repo / "artifacts" / "review-1.txt").read_text(encoding="utf-8")
    assert "Review base preflight failed" in artifact_text
    assert "git merge-base HEAD main" in artifact_text


def test_doctor_json_reports_invalid_base_without_invoking_runner(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    def runner(*_args, **_kwargs):
        raise AssertionError("revrem doctor must not invoke the Codex runner")

    monkeypatch.setattr(runner_mod, "default_runner", runner)

    exit_code = cli_main.main(
        ["doctor", "--base", "missing", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.invalid_base"}
    assert captured.err == ""


def test_live_cli_preflight_blocks_before_review_invocation(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    def fail_review(*_args, **_kwargs):
        raise AssertionError("review must not run when live preflight blocks")

    # B2f: patch ReviewAdapter.execute instead of the legacy run_codex_review shim
    import code_review_loop.adapters.review as _review_mod
    monkeypatch.setattr(_review_mod.ReviewAdapter, "execute", fail_review)

    exit_code = cli_main.main(
        ["--base", "missing", "--codex-bin", "git", "--artifact-dir", "artifacts"]
    )

    diagnostics_payload = json.loads((repo / "artifacts" / "diagnostics.json").read_text(encoding="utf-8"))
    summary = json.loads((repo / "artifacts" / "summary.json").read_text(encoding="utf-8"))

    assert exit_code == 4
    assert diagnostics_payload["status"] == "blocking"
    assert {issue["code"] for issue in diagnostics_payload["issues"]} == {
        "revrem.preflight.invalid_base"
    }
    assert diagnostics_payload["issues"][0]["fingerprint"].startswith("f1:")
    assert summary["stopped_reason"] == "setup_failed"
    assert "preflight diagnostics found blocking issue" in capsys.readouterr().err


def test_doctor_json_reports_missing_git_as_blocking_issue(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(runner_mod.diagnostics.subprocess, "run", fake_run)

    exit_code = cli_main.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.git_not_found"}
    assert captured.err == ""


def test_doctor_text_reports_ok_for_valid_repo(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    exit_code = cli_main.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "text"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK: revrem.preflight.ok" in captured.out
    assert captured.err == ""


def test_doctor_validates_default_artifact_dir_when_unset(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    blocked_artifact_dir = repo / ".revrem" / "runs" / "blocked-default"
    blocked_artifact_dir.parent.mkdir(parents=True)
    blocked_artifact_dir.write_text("blocked\n", encoding="utf-8")
    from code_review_loop.cli.commands import doctor as doctor_command

    monkeypatch.setattr(doctor_command, "default_artifact_dir", lambda: blocked_artifact_dir)

    exit_code = cli_main.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {
        "revrem.preflight.artifact_dir_not_writable",
    }
    assert payload["issues"][0]["evidence"]["artifact_dir"] == str(blocked_artifact_dir)
    assert captured.err == ""


def test_doctor_does_not_create_default_artifact_dir_on_clean_repo(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    default_artifact_dir = repo / ".revrem" / "runs" / "default-run"
    from code_review_loop.cli.commands import doctor as doctor_command

    monkeypatch.setattr(doctor_command, "default_artifact_dir", lambda: default_artifact_dir)

    exit_code = cli_main.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert not (repo / ".revrem").exists()
    assert captured.err == ""


def test_doctor_strict_returns_exit_code_6_for_warnings(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.unbounded]
description = "Explicitly unbounded review timeout"

[profiles.unbounded.review]
timeout_seconds = 0
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    exit_code = cli_main.main(
        [
            "doctor",
            "--profile",
            "unbounded",
            "--base",
            "main",
            "--codex-bin",
            "git",
            "--strict",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 6
    assert payload["status"] == "ok"
    assert {issue["code"] for issue in payload["issues"]} == {
        "revrem.preflight.timeout_disabled",
    }
    assert captured.err == ""


def test_doctor_profile_blocks_repo_root_artifact_dir_in_commit_mode(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.commit-root]
description = "Commit mode with a root artifact dir"

[profiles.commit-root.commit]
enabled = true

[profiles.commit-root.output]
artifact_dir = "."
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    exit_code = cli_main.main(
        ["doctor", "--profile", "commit-root", "--base", "main", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {
        "revrem.preflight.artifact_dir_resolves_to_repo_root",
    }
    assert payload["issues"][0]["evidence"]["artifact_dir"] == "."
    assert captured.err == ""


def test_doctor_profile_allows_reserved_harnesses_without_profile_error(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.smoke]
description = "Smoke profile"

[profiles.smoke.review]
harness = "claude"

[profiles.smoke.remediation]
harness = "gemini"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    exit_code = cli_main.main(
        ["doctor", "--profile", "smoke", "--base", "main", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.ok"}
    assert captured.err == ""


def test_doctor_profile_skips_unused_route_harnesses_when_routing_disabled(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.smoke]
description = "Smoke profile"

[profiles.smoke.review]
harness = "claude"

[profiles.smoke.remediation]
harness = "claude"

[profiles.smoke.triage]
enabled = true
harness = "claude"

[profiles.smoke.triage.routing]
enabled = false

[profiles.smoke.triage.routes.future]
harness = "gemini"
""",
        encoding="utf-8",
    )

    def fake_which(executable: str):
        if executable == "claude":
            return "/usr/bin/claude"
        return None

    monkeypatch.setattr(runner_mod.diagnostics.shutil, "which", fake_which)
    monkeypatch.chdir(repo)

    exit_code = cli_main.main(
        ["doctor", "--profile", "smoke", "--base", "main", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.ok"}
    assert captured.err == ""


def test_bundle_bug_report_cli_blocks_no_redact_without_explicit_risk_ack(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    exit_code = cli_main.main(["bundle-bug-report", str(run_dir), "--no-redact"])

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "--no-redact requires --i-understand-the-risks" in captured.err


def test_bundle_bug_report_cli_writes_output_path(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        '{"schema_version":"1.0","run_id":"run-123"}\n',
        encoding="utf-8",
    )
    (run_dir / "check-1.txt").write_text("Authorization: Bearer secret-token\n", encoding="utf-8")
    output = tmp_path / "bundle.tar.gz"

    exit_code = cli_main.main(["bundle-bug-report", str(run_dir), "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == str(output.resolve())
    assert output.is_file()
