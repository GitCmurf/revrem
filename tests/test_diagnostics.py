from __future__ import annotations

import subprocess
from pathlib import Path

from code_review_loop import diagnostics


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _issue_codes(issues: list[diagnostics.DiagnosticIssue]) -> set[str]:
    return {issue.code for issue in issues}


def test_run_doctor_reports_ok_for_valid_repo(tmp_path):
    repo = _make_repo(tmp_path)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(cwd=repo, base="main", codex_bin="git")
    )

    assert _issue_codes(issues) == {"revrem.preflight.ok"}
    assert not diagnostics.has_blocking_issue(issues)
    assert diagnostics.doctor_payload(issues)["status"] == "ok"


def test_run_doctor_reports_invalid_base(tmp_path):
    repo = _make_repo(tmp_path)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(cwd=repo, base="missing", codex_bin="git")
    )

    assert "revrem.preflight.invalid_base" in _issue_codes(issues)
    assert diagnostics.has_blocking_issue(issues)


def test_run_doctor_blocks_dirty_worktree_in_commit_mode(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("# Changed\n", encoding="utf-8")

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            commit_after_remediation=True,
        )
    )

    assert "revrem.preflight.dirty_worktree_commit_mode" in _issue_codes(issues)


def test_run_doctor_blocks_repo_root_artifact_dir_in_commit_mode(tmp_path):
    repo = _make_repo(tmp_path)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            artifact_dir=Path("."),
            commit_after_remediation=True,
        )
    )

    assert "revrem.preflight.artifact_dir_resolves_to_repo_root" in _issue_codes(issues)
    assert diagnostics.has_blocking_issue(issues)


def test_run_doctor_reports_missing_check_command(tmp_path):
    repo = _make_repo(tmp_path)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            check_commands=("definitely-missing-revrem-check --flag",),
        )
    )

    assert "revrem.preflight.check_command_not_found" in _issue_codes(issues)


def test_run_doctor_reports_unparseable_check_command(tmp_path):
    repo = _make_repo(tmp_path)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            check_commands=('pytest -q "unterminated',),
        )
    )

    assert "revrem.preflight.check_command_unparseable" in _issue_codes(issues)
