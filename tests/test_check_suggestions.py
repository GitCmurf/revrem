from __future__ import annotations

import json

from code_review_loop import check_suggestions
from code_review_loop.cli.main import main as cli_main


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


def test_checks_suggest_json_cli(tmp_path, capsys):
    (tmp_path / "go.mod").write_text("module example.test/repo\n", encoding="utf-8")

    rc = cli_main(["checks", "suggest", "--cwd", str(tmp_path), "--format", "json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert payload["suggestions"][0]["command"] == "go test ./..."


def test_checks_suggest_text_cli_reports_empty_repo(tmp_path, capsys):
    rc = cli_main(["checks", "suggest", "--cwd", str(tmp_path), "--format", "text"])

    assert rc == 0
    assert capsys.readouterr().out == "No check suggestions found.\n"
