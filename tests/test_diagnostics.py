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


def test_run_doctor_resolves_relative_artifact_dir_against_doctor_cwd(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    process_cwd = tmp_path / "process-cwd"
    process_cwd.mkdir()
    monkeypatch.chdir(process_cwd)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            artifact_dir=Path("artifacts"),
        )
    )

    assert _issue_codes(issues) == {"revrem.preflight.ok"}
    assert (repo / "artifacts").is_dir()
    assert not (process_cwd / "artifacts").exists()


def test_run_doctor_does_not_create_default_artifact_dir(tmp_path):
    repo = _make_repo(tmp_path)
    default_artifact_dir = repo / ".revrem" / "runs" / "default-run"

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            artifact_dir=default_artifact_dir,
            artifact_dir_is_default=True,
        )
    )

    assert _issue_codes(issues) == {"revrem.preflight.ok"}
    assert not (repo / ".revrem").exists()


def test_run_doctor_blocks_default_artifact_dir_when_parent_is_unwritable(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    default_artifact_dir = repo / ".revrem" / "runs" / "default-run"

    original_write_text = Path.write_text

    def fake_write_text(self: Path, data: str, encoding: str | None = None, errors: str | None = None, newline: str | None = None):
        if self.name == ".revrem-doctor-write-test":
            raise PermissionError("blocked")
        return original_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            artifact_dir=default_artifact_dir,
            artifact_dir_is_default=True,
        )
    )

    assert _issue_codes(issues) == {"revrem.preflight.artifact_dir_not_writable"}
    assert issues[0].evidence["resolved_artifact_dir"] == str(repo / ".revrem" / "runs" / "default-run")
    assert not (repo / ".revrem").exists()


def test_run_doctor_blocks_default_artifact_dir_when_path_component_is_file(tmp_path):
    repo = _make_repo(tmp_path)
    default_artifact_dir = repo / ".revrem" / "runs" / "default-run"
    repo.joinpath(".revrem").write_text("blocked\n", encoding="utf-8")

    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=repo,
            base="main",
            codex_bin="git",
            artifact_dir=default_artifact_dir,
            artifact_dir_is_default=True,
        )
    )

    assert _issue_codes(issues) == {"revrem.preflight.artifact_dir_not_writable"}
    assert issues[0].evidence["error"] == str(repo / ".revrem")


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
