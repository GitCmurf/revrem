from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "code_review_loop"


def test_production_source_has_no_wave_c_migration_scar_language() -> None:
    forbidden = (
        "cli._run_loop",
        "legacy shim",
        "back-compat",
        "MODULE.",
        "monkeypatch surface",
        "Optional so phases",
    )
    offenders: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            if phrase in text:
                offenders.append(f"{path.relative_to(ROOT)}: {phrase}")

    assert offenders == []


def test_cli_main_routes_loop_execution_through_application_api() -> None:
    text = (SOURCE_ROOT / "cli" / "main.py").read_text(encoding="utf-8")

    assert "from code_review_loop import application" in text
    assert "application.run_review_loop(config)" in text
    assert "runner.run_loop" not in text
    assert "from code_review_loop import runner" not in text


def test_phase_adapters_have_no_impl_split() -> None:
    impl_modules = sorted((SOURCE_ROOT / "adapters").glob("_*_impl.py"))

    assert impl_modules == []


def test_runner_imports_shared_phase_support_helpers() -> None:
    text = (SOURCE_ROOT / "runner.py").read_text(encoding="utf-8")

    assert "from code_review_loop.adapters.phase_support import" in text
    for helper in (
        "progress_event",
        "write_artifact",
        "ensure_model_budget",
        "build_commit_message_command",
        "sanitize_commit_message",
    ):
        assert f"def {helper}(" not in text


def test_production_modules_do_not_hide_dead_imports_with_self_aliases() -> None:
    offenders: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                if alias.asname == alias.name:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {alias.name} as {alias.asname}")

    assert offenders == []


def test_phase_adapters_do_not_alias_support_as_cli() -> None:
    offenders: list[str] = []
    for path in (SOURCE_ROOT / "adapters").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "phase_support as _cli" in text or "_cli." in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
