from __future__ import annotations

from pathlib import Path

from code_review_loop.cli.commands.registry import build_subcommand_registry

_ROOT = Path(__file__).resolve().parents[1]


def test_cli_main_is_closed_to_concrete_subcommand_names() -> None:
    source = (_ROOT / "src" / "code_review_loop" / "cli" / "main.py").read_text(encoding="utf-8")

    leaked = sorted(
        name
        for name in build_subcommand_registry()
        if f'"{name}"' in source or f"'{name}'" in source
    )

    assert leaked == []


def test_headless_tests_do_not_use_default_subprocess_runner() -> None:
    for relative in (
        "tests/support/headless.py",
        "tests/test_application_headless_integration.py",
    ):
        source = (_ROOT / relative).read_text(encoding="utf-8")
        assert "default_runner" not in source
