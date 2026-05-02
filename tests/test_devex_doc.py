from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/70-devex/devex-001-using-code-review-loop.md"


def test_devex_front_matter_version_matches_latest_history_row():
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "---"

    front_matter_end = lines.index("---", 1)
    front_matter = lines[1:front_matter_end]

    version_line = next(line for line in front_matter if line.startswith("version: "))
    assert version_line == "version: '0.3'"

    history_start = lines.index("## Version History")
    history_rows = [
        line
        for line in lines[history_start + 1 :]
        if line.startswith("| ") and not line.startswith("| Version ") and not line.startswith("|---")
    ]

    latest_row = history_rows[0]
    latest_version = latest_row.split("|")[1].strip()

    assert latest_version == "0.3"
