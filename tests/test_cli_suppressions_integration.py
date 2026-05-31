from __future__ import annotations

import json
import subprocess
from importlib import import_module
from pathlib import Path

from code_review_loop import suppressions

cli_main = import_module("code_review_loop.cli.main")


def run_git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_suppress_cli_add_check_remove_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("REVREM_SUPPRESSION_ACTOR", "tester")

    assert cli_main.main(
        [
            "suppress",
            "add",
            "f1:abc123",
            "--summary",
            "Accepted finding",
            "--rationale",
            "Tracked in issue 123.",
            "--severity",
            "medium",
        ]
    ) == 0
    assert cli_main.main(["suppress", "check", "f1:abc123"]) == 0
    assert cli_main.main(["suppress", "remove", "f1:abc123"]) == 0
    assert cli_main.main(["suppress", "check", "f1:abc123"]) == 2
    assert "added f1:abc123" in capsys.readouterr().out


def test_doctor_warns_about_expired_and_unsupported_suppressions(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    suppressions.write_entries(
        suppressions.repo_suppressions_path(tmp_path),
        [
            suppressions.make_entry(
                fingerprint="f1:expired",
                summary="Expired finding",
                rationale="No longer valid.",
                severity="medium",
                scope="repo",
                expires_at="2026-05-01T00:00:00Z",
                critical_override=False,
                created_at="2026-04-01T00:00:00Z",
            ),
            suppressions.make_entry(
                fingerprint="f2:future",
                summary="Unsupported version",
                rationale="Created by a future migration.",
                severity="medium",
                scope="repo",
                expires_at=None,
                critical_override=False,
                created_at="2026-05-12T00:00:00Z",
            ),
        ],
    )

    code = cli_main.main(["doctor", "--format", "json", "--base", "HEAD"])

    assert code in {4, 6}
    output = capsys.readouterr().out
    assert "revrem.suppressions.expired" in output
    assert "revrem.suppressions.unsupported_fingerprint_version" in output


def test_doctor_warns_about_unreadable_optional_suppression_state(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    unreadable_path = suppressions.user_suppressions_path(home)

    def fake_stale_entries(path, *, now=None):
        if path == unreadable_path:
            raise PermissionError("blocked")
        return ([], [])

    monkeypatch.setattr(suppressions, "stale_entries", fake_stale_entries)

    exit_code = cli_main.main(["doctor", "--base", "HEAD", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert "revrem.suppressions.invalid_file" in captured.out
