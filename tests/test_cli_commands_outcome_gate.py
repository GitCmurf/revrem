"""Outcome ADT grep-gate (REVREM-TASK-003 Wave C1b).

Subcommand modules under ``code_review_loop.cli.commands`` must return their
exit codes through the ``CommandOutcome`` ADT (``CommandOk`` / ``CommandFailed``)
rather than bare integer literals. The gate keeps the C5 / C1b contract
machine-enforced so a future contributor cannot quietly reintroduce raw
``return 1`` after the C1a sweep.

Lines containing the inline annotation ``# outcome-exempt: <reason>`` are
ignored; this is the documented escape hatch for cases that cannot be expressed
through the ADT (today: none).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_CLI_DIR = Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "cli"
_COMMANDS_DIR = _CLI_DIR / "commands"
_BARE_RETURN_INT = re.compile(r"^\s*return\s+-?[0-9]+\b")
_EXEMPT = "outcome-exempt:"


def _command_modules() -> list[Path]:
    modules = [(_CLI_DIR / "main.py")]
    modules.extend(sorted(p for p in _COMMANDS_DIR.glob("*.py") if p.name != "__init__.py"))
    return modules


def _violations(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _BARE_RETURN_INT.match(line) and _EXEMPT not in line:
            out.append((lineno, line.strip()))
    return out


@pytest.mark.parametrize("module_path", _command_modules(), ids=lambda p: p.name)
def test_no_bare_return_int_in_command_modules(module_path: Path) -> None:
    violations = _violations(module_path)
    assert not violations, (
        f"Bare integer return in {module_path.relative_to(_CLI_DIR.parent)} "
        f"(use CommandOk()/CommandFailed(exit_code=N).exit_code, or annotate "
        f"'# outcome-exempt: <reason>'):\n"
        + "\n".join(f"  L{n}: {text}" for n, text in violations)
    )
