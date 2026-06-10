"""Read-only repository check discovery for profile authoring."""

from __future__ import annotations

import configparser
import json
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckSuggestion:
    command: str
    source: str
    phase: str
    confidence: str
    requires_network: bool
    notes: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def suggest_checks(cwd: Path) -> list[CheckSuggestion]:
    root = cwd.resolve()
    suggestions: list[CheckSuggestion] = []
    suggestions.extend(_package_json_suggestions(root))
    suggestions.extend(_python_suggestions(root))
    suggestions.extend(_pre_commit_suggestions(root))
    suggestions.extend(_tox_nox_suggestions(root))
    suggestions.extend(_rust_suggestions(root))
    suggestions.extend(_go_suggestions(root))
    suggestions.extend(_git_hook_suggestions(root))
    return _dedupe_suggestions(suggestions)


def suggestions_payload(cwd: Path) -> dict[str, object]:
    suggestions = [suggestion.to_dict() for suggestion in suggest_checks(cwd)]
    return {
        "schema_version": "1.0",
        "cwd": str(cwd.resolve()),
        "suggestions": suggestions,
    }


def render_suggestions_text(cwd: Path) -> str:
    suggestions = suggest_checks(cwd)
    if not suggestions:
        return "No check suggestions found.\n"
    lines = ["Suggested checks:"]
    for suggestion in suggestions:
        network = "network" if suggestion.requires_network else "local"
        lines.append(
            f"- {suggestion.command} "
            f"[{suggestion.phase}, {suggestion.confidence}, {network}; "
            f"source={suggestion.source}]"
        )
        if suggestion.notes:
            lines.append(f"  {suggestion.notes}")
    return "\n".join(lines) + "\n"


def _package_json_suggestions(root: Path) -> list[CheckSuggestion]:
    path = root / "package.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = raw.get("scripts")
    if not isinstance(scripts, dict):
        return []
    manager = _node_package_manager(root)
    script_phases = {
        "test": "test",
        "lint": "lint",
        "typecheck": "typecheck",
        "check": "test",
        "build": "build",
    }
    suggestions: list[CheckSuggestion] = []
    for script, phase in script_phases.items():
        if isinstance(scripts.get(script), str):
            suggestions.append(
                CheckSuggestion(
                    command=f"{manager} run {script}",
                    source="package.json",
                    phase=phase,
                    confidence="high",
                    requires_network=False,
                    notes=f"package.json defines scripts.{script}",
                )
            )
    return suggestions


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _python_suggestions(root: Path) -> list[CheckSuggestion]:
    suggestions: list[CheckSuggestion] = []
    pyproject = root / "pyproject.toml"
    has_pytest_config = False
    if pyproject.is_file():
        try:
            raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
        tool = raw.get("tool")
        has_pytest_config = isinstance(tool, dict) and isinstance(
            tool.get("pytest"), dict
        )
    has_pytest_file = any(
        (root / name).is_file() for name in ("pytest.ini", "setup.cfg", "tox.ini")
    )
    has_python_project = any(
        (root / name).is_file()
        for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
    )
    if has_pytest_config or has_pytest_file or (has_python_project and (root / "tests").is_dir()):
        suggestions.append(
            CheckSuggestion(
                command="pytest -q",
                source="pytest",
                phase="test",
                confidence="high" if has_pytest_config or has_pytest_file else "medium",
                requires_network=False,
                notes="Python test surface detected.",
            )
        )
    if pyproject.is_file() and _pyproject_has_ruff(pyproject):
        suggestions.append(
            CheckSuggestion(
                command="ruff check .",
                source="pyproject.toml",
                phase="lint",
                confidence="high",
                requires_network=False,
                notes="pyproject.toml contains Ruff configuration.",
            )
        )
    return suggestions


def _pyproject_has_ruff(path: Path) -> bool:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = raw.get("tool")
    return isinstance(tool, dict) and "ruff" in tool


def _pre_commit_suggestions(root: Path) -> list[CheckSuggestion]:
    if not (root / ".pre-commit-config.yaml").is_file():
        return []
    return [
        CheckSuggestion(
            command="pre-commit run --all-files",
            source=".pre-commit-config.yaml",
            phase="pre-commit",
            confidence="high",
            requires_network=True,
            notes="First run may install hook environments.",
        )
    ]


def _tox_nox_suggestions(root: Path) -> list[CheckSuggestion]:
    suggestions: list[CheckSuggestion] = []
    if (root / "tox.ini").is_file():
        suggestions.append(
            CheckSuggestion(
                command="tox",
                source="tox.ini",
                phase="test",
                confidence="high",
                requires_network=True,
                notes="tox may create or update isolated environments.",
            )
        )
    if (root / "noxfile.py").is_file():
        suggestions.append(
            CheckSuggestion(
                command="nox",
                source="noxfile.py",
                phase="test",
                confidence="high",
                requires_network=True,
                notes="nox may create or update isolated environments.",
            )
        )
    return suggestions


def _rust_suggestions(root: Path) -> list[CheckSuggestion]:
    if not (root / "Cargo.toml").is_file():
        return []
    return [
        CheckSuggestion(
            command="cargo test",
            source="Cargo.toml",
            phase="test",
            confidence="high",
            requires_network=True,
            notes="Cargo may fetch crates when dependencies are missing.",
        )
    ]


def _go_suggestions(root: Path) -> list[CheckSuggestion]:
    if not (root / "go.mod").is_file():
        return []
    return [
        CheckSuggestion(
            command="go test ./...",
            source="go.mod",
            phase="test",
            confidence="high",
            requires_network=True,
            notes="Go may download modules when the module cache is cold.",
        )
    ]


def _git_hook_suggestions(root: Path) -> list[CheckSuggestion]:
    hooks_dirs = [root / ".git" / "hooks"]
    configured = _core_hooks_path(root)
    if configured is not None:
        hooks_dirs.insert(0, configured if configured.is_absolute() else root / configured)
    suggestions: list[CheckSuggestion] = []
    for hooks_dir in hooks_dirs:
        for hook_name, phase in (("pre-commit", "pre-commit"), ("pre-push", "pre-push")):
            hook = hooks_dir / hook_name
            if hook.is_file() and os.access(hook, os.X_OK):
                suggestions.append(
                    CheckSuggestion(
                        command=str(hook),
                        source=str(hook.relative_to(root)) if _is_relative_to(hook, root) else str(hook),
                        phase=phase,
                        confidence="medium",
                        requires_network=False,
                        notes="Executable Git hook detected; inspect before using as a RevRem check.",
                    )
                )
    return suggestions


def _core_hooks_path(root: Path) -> Path | None:
    git_config = root / ".git" / "config"
    if not git_config.is_file():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(git_config, encoding="utf-8")
    except configparser.Error:
        return None
    if not parser.has_section("core") or not parser.has_option("core", "hookspath"):
        return None
    return Path(parser.get("core", "hookspath"))


def _dedupe_suggestions(suggestions: list[CheckSuggestion]) -> list[CheckSuggestion]:
    seen: set[str] = set()
    result: list[CheckSuggestion] = []
    for suggestion in suggestions:
        if suggestion.command in seen:
            continue
        seen.add(suggestion.command)
        result.append(suggestion)
    return result


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
