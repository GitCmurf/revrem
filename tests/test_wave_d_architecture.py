from __future__ import annotations

import ast
from pathlib import Path

from code_review_loop.cli.commands.registry import build_subcommand_registry

_ROOT = Path(__file__).resolve().parents[1]


def test_cli_main_is_closed_to_concrete_subcommand_names() -> None:
    source = (_ROOT / "src" / "code_review_loop" / "cli" / "main.py").read_text(encoding="utf-8")
    string_literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    leaked = sorted(name for name in build_subcommand_registry() if name in string_literals)

    assert leaked == []
