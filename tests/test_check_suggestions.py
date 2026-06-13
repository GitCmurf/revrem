from __future__ import annotations

import json
import subprocess
from pathlib import Path

from code_review_loop import check_suggestions
from code_review_loop.cli.main import main as cli_main


def _init_repo(path: Path) -> None:
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "revrem@example.test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "RevRem Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    _init_repo(repo)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(linked), "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert (linked / ".git").is_file()
    return repo, linked


def test_suggest_checks_detects_node_package_scripts(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "test": "vitest",
                    "lint": "eslint .",
                    "typecheck": "tsc --noEmit",
                }
            }
        ),
        encoding="utf-8",
    )

    suggestions = check_suggestions.suggest_checks(tmp_path)

    assert [item.command for item in suggestions] == [
        "pnpm run test",
        "pnpm run lint",
        "pnpm run typecheck",
    ]
    assert all(item.source == "package.json" for item in suggestions)
    assert all(item.requires_network is False for item in suggestions)
    assert all(item.estimated_cost == "local" for item in suggestions)


def test_suggest_checks_detects_python_and_precommit(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
""",
        encoding="utf-8",
    )
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")

    suggestions = check_suggestions.suggest_checks(tmp_path)
    by_command = {item.command: item for item in suggestions}

    assert by_command["pytest -q"].confidence == "high"
    assert by_command["ruff check ."].source == "pyproject.toml"
    assert by_command["pre-commit run --all-files"].requires_network is True


def test_suggest_checks_detects_executable_git_hooks(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-push"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | 0o111)

    suggestions = check_suggestions.suggest_checks(tmp_path)

    assert any(item.phase == "pre-push" and item.command.endswith("pre-push") for item in suggestions)


def test_suggest_checks_skips_revrem_managed_git_hooks(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n# REVREM_MANAGED_HOOK: begin\nexec revrem --base main\n# REVREM_MANAGED_HOOK: end\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | 0o111)

    suggestions = check_suggestions.suggest_checks(tmp_path)

    assert all(item.command != str(hook) for item in suggestions)


def test_suggest_checks_detects_githooks_directory(tmp_path):
    hooks = tmp_path / ".githooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | 0o111)

    suggestions = check_suggestions.suggest_checks(tmp_path)
    by_command = {item.command: item for item in suggestions}

    command = str(hook)
    assert by_command[command].source == ".githooks/pre-commit"
    assert by_command[command].phase == "pre-commit"
    assert by_command[command].estimated_cost == "unknown"


def test_suggest_checks_detects_default_git_hooks_in_linked_worktree(tmp_path):
    _repo, linked = _linked_worktree(tmp_path)
    hooks_dir = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=linked,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hooks = Path(hooks_dir)
    if not hooks.is_absolute():
        hooks = linked / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | 0o111)

    suggestions = check_suggestions.suggest_checks(linked)

    assert any(item.command == str(hook) and item.phase == "pre-push" for item in suggestions)


def test_suggest_checks_detects_configured_hooks_path_in_linked_worktree(tmp_path):
    repo, linked = _linked_worktree(tmp_path)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".custom-hooks"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    hooks = linked / ".custom-hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | 0o111)

    suggestions = check_suggestions.suggest_checks(linked)

    assert any(
        item.command == str(hook) and item.phase == "pre-commit" for item in suggestions
    )


def test_suggest_checks_discovers_root_markers_from_nested_subdirectory(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )
    nested = repo / "nested" / "deeper"
    nested.mkdir(parents=True)

    suggestions = check_suggestions.suggest_checks(nested)

    assert [item.command for item in suggestions] == ["npm run test"]


def test_marker_root_falls_back_to_resolved_cwd_outside_git(tmp_path, monkeypatch):
    nested = tmp_path / "outside" / "repo"
    nested.mkdir(parents=True)
    monkeypatch.setattr(check_suggestions.git_hooks, "worktree_root", lambda _cwd: None)

    assert check_suggestions._marker_root(nested) == nested.resolve()


def test_checks_suggest_json_cli(tmp_path, capsys):
    (tmp_path / "go.mod").write_text("module example.test/repo\n", encoding="utf-8")

    rc = cli_main(["checks", "suggest", "--cwd", str(tmp_path), "--format", "json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert payload["suggestions"][0]["command"] == "go test ./..."
    assert payload["suggestions"][0]["estimated_cost"] == "network_setup"


def test_doctor_checks_json_cli_reuses_suggestions(tmp_path, capsys):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n", encoding="utf-8")

    rc = cli_main(["doctor", "checks", "--cwd", str(tmp_path), "--format", "json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["suggestions"][0]["command"] == "cargo test"


def test_checks_suggest_text_cli_reports_empty_repo(tmp_path, capsys):
    rc = cli_main(["checks", "suggest", "--cwd", str(tmp_path), "--format", "text"])

    assert rc == 0
    assert capsys.readouterr().out == "No check suggestions found.\n"
