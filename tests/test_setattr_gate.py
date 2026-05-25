"""Grep-gate: no object.__setattr__(config, ...) calls in cli (REVREM-TASK-003 B0b).

The ``cli`` module became a package in Wave C1a; the legacy body lives in
``cli/__init__.py`` until Wave C lifts it out, so the gate scans the package
init.
"""
import pathlib
import re

CLI_PATH = (
    pathlib.Path(__file__).parent.parent / "src" / "code_review_loop" / "cli" / "__init__.py"
)


def test_no_config_setattr_in_cli():
    source = CLI_PATH.read_text(encoding="utf-8")
    matches = [
        (i + 1, line)
        for i, line in enumerate(source.splitlines())
        if re.search(r'object\.__setattr__\(config', line)
    ]
    assert matches == [], (
        f"Found {len(matches)} object.__setattr__(config, ...) call(s) in cli/__init__.py. "
        "Offending lines:\n"
        + "\n".join(f"  {lineno}: {line}" for lineno, line in matches)
    )
