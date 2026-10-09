"""Golden-master snapshot helper (REVREM-TASK-003 C3/A2).

``assert_snapshot(name, value)`` compares a normalized value against a committed
JSON snapshot under ``tests/snapshots/``. Any difference is a test failure with
a unified diff — the C3 "fail on unledgered change" instrument. Regenerate
intentionally with ``REVREM_UPDATE_SNAPSHOTS=1`` (or ``update=True``) after
recording the change in the behaviour ledger.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots"


def _serialize(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def assert_snapshot(name: str, value: Any, *, update: bool = False) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    serialized = _serialize(value)
    should_update = update or os.environ.get("REVREM_UPDATE_SNAPSHOTS") == "1"

    if should_update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
        if not path.exists():  # pragma: no cover - defensive
            raise AssertionError(f"failed to write snapshot {path}")
        return

    expected = path.read_text(encoding="utf-8")
    if serialized != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                serialized.splitlines(keepends=True),
                fromfile=f"{name}.json (committed)",
                tofile=f"{name}.json (actual)",
            )
        )
        raise AssertionError(
            f"Golden-master snapshot '{name}' changed. If intentional, record it "
            f"in the behaviour ledger and regenerate with REVREM_UPDATE_SNAPSHOTS=1.\n{diff}"
        )


def normalize_svg(svg: str) -> str:
    # Rich's SVG renderer emits a whitespace-only separator line between SVG
    # groups. Strip that line so committed snapshots stay CI-clean without
    # changing visible rendering content.
    svg = re.sub(r"(?m)^[ \t]+(?:\n|$)", "", svg)
    normalized = svg.replace("&#160;", " ")
    normalized = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?\b", "<time>", normalized)
    normalized = re.sub(r"pytest-\d+", "pytest-N", normalized)
    normalized = re.sub(r"terminal-\d+", "terminal-ID", normalized)
    return normalized


def assert_svg_snapshot(
    name: str,
    svg: str,
    *,
    update: bool = False,
    normalize_theme_colors: bool = False,
) -> None:
    assert svg.startswith("<svg")
    assert len(svg) > 1000
    path = SNAPSHOT_DIR / f"{name}.svg"
    should_update = update or os.environ.get("REVREM_UPDATE_SNAPSHOTS") == "1"
    comparison_svg = _normalize_svg_theme_colors(svg) if normalize_theme_colors else svg
    if should_update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(comparison_svg, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    comparison_expected = (
        _normalize_svg_theme_colors(expected) if normalize_theme_colors else expected
    )
    if comparison_svg != comparison_expected:
        diff = "".join(
            difflib.unified_diff(
                comparison_expected.splitlines(keepends=True),
                comparison_svg.splitlines(keepends=True),
                fromfile=f"{path} (committed)",
                tofile=f"{path} (actual)",
            )
        )
        raise AssertionError(f"SVG snapshot changed for {name}:\n{diff}")


def _normalize_svg_theme_colors(svg: str) -> str:
    return re.sub(r"#[0-9a-fA-F]{6}\b", "#THEME", svg)
