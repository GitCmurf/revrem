"""Read-only repository check discovery for profile authoring."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from code_review_loop import git_hooks
from code_review_loop.cli.commands.install_hooks import MANAGED_BEGIN, MANAGED_END


@dataclass(frozen=True)
class CheckSuggestion:
    command: str
    source: str
    phase: str
    confidence: str
    requires_network: bool
    estimated_cost: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def suggest_checks(cwd: Path) -> list[CheckSuggestion]:
    root = _marker_root(cwd)
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


def _marker_root(cwd: Path) -> Path:
    root = git_hooks.worktree_root(cwd)
    if root is not None:
        return root
    return cwd.resolve()


def _package_json_suggestions(root: Path) -> list[CheckSuggestion]:
    path = root / "package.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
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
                    estimated_cost="local",
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
    raw: dict[str, object] = {}
    if pyproject.is_file():
        try:
            raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
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
                estimated_cost="local",
                notes="Python test surface detected.",
            )
        )
    tool_section = raw.get("tool")
    if pyproject.is_file() and isinstance(tool_section, dict) and "ruff" in tool_section:
        suggestions.append(
            CheckSuggestion(
                command="ruff check .",
                source="pyproject.toml",
                phase="lint",
                confidence="high",
                requires_network=False,
                estimated_cost="local",
                notes="pyproject.toml contains Ruff configuration.",
            )
        )
    return suggestions


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
            estimated_cost="network_setup",
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
                estimated_cost="network_setup",
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
                estimated_cost="network_setup",
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
            estimated_cost="network_setup",
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
            estimated_cost="network_setup",
            notes="Go may download modules when the module cache is cold.",
        )
    ]


def _git_hook_suggestions(root: Path) -> list[CheckSuggestion]:
    hooks_dirs = [root / ".githooks"]
    configured = git_hooks.configured_hooks_path(root)
    if configured is not None:
        hooks_dirs.append(configured)
    default_hooks = git_hooks.default_hooks_dir(root)
    if default_hooks is not None:
        hooks_dirs.append(default_hooks)
    hooks_dirs.append(root / ".git" / "hooks")
    suggestions: list[CheckSuggestion] = []
    for hooks_dir in _dedupe_paths(hooks_dirs):
        for hook_name, phase in (("pre-commit", "pre-commit"), ("pre-push", "pre-push")):
            hook = hooks_dir / hook_name
            # RevRem-managed hooks call back into ``revrem``; suggest only
            # unmanaged executable hooks to avoid recursive execution.
            if (
                hook.is_file()
                and os.access(hook, os.X_OK)
                and not _is_revrem_managed_hook(hook)
            ):
                suggestions.append(
                    CheckSuggestion(
                        command=str(hook),
                        source=(
                            str(hook.resolve().relative_to(root.resolve()))
                            if _is_relative_to(hook, root)
                            else str(hook)
                        ),
                        phase=phase,
                        confidence="medium",
                        requires_network=False,
                        estimated_cost="unknown",
                        notes="Executable Git hook detected; inspect before using as a RevRem check.",
                    )
                )
    return suggestions


def _is_revrem_managed_hook(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return MANAGED_BEGIN in text and MANAGED_END in text


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


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
