from __future__ import annotations

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
