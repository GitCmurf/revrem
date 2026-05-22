"""Grep-gate: no object.__setattr__(config, ...) calls in cli.py (REVREM-TASK-003 B0b)."""
import re
import pathlib

CLI_PATH = pathlib.Path(__file__).parent.parent / "src" / "code_review_loop" / "cli.py"


def test_no_config_setattr_in_cli():
    source = CLI_PATH.read_text(encoding="utf-8")
    matches = [
        (i + 1, line)
        for i, line in enumerate(source.splitlines())
        if re.search(r'object\.__setattr__\(config', line)
    ]
    assert matches == [], (
        f"Found {len(matches)} object.__setattr__(config, ...) call(s) in cli.py. "
        "Offending lines:\n"
        + "\n".join(f"  {lineno}: {line}" for lineno, line in matches)
    )
