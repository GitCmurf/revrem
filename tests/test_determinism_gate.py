"""Determinism grep-gate (REVREM-TASK-003 Contract C6).

The review-loop engine must read wall-clock time, monotonic time, and run-scoped
identifiers through injected seams (``Clock`` / ``RunIdentity``), not raw module
calls — otherwise its machine-contract output (summary JSON, ``events.jsonl``)
cannot be pinned by the golden-master suite (A2).

This gate scans the engine-path files for raw ``datetime.now`` / ``time.monotonic``
/ ``uuid.uuid4`` reads. Every such read must either be routed through a seam or
be explicitly annotated ``# det-exempt: <reason>`` on the same line. The honest
carve-outs (real-time signal debounce, subprocess timeout deadlines, human-only
display timestamps, and the event default-factory fallback) are exempt by
annotation; anything else fails.

The gate is line-number-free so it survives edits: it keys off the inline marker,
not positions. Budget timing (``budgets.py``) is intentionally out of scope this
wave — its wall-time fields are normalized by the A2 comparator instead (see the
behaviour ledger entry for A1).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src" / "code_review_loop"

# Engine-path files whose nondeterminism feeds the machine contract.
# ``cli`` became a package in Wave C1a; its ``__init__.py`` carries the
# legacy God-object body until the rest of Wave C lifts it out.
SCANNED_FILES = ("cli/__init__.py", "events.py")

_RAW_READ = re.compile(r"datetime\.now|datetime\.utcnow|time\.monotonic|uuid\.uuid4")
_EXEMPT = "det-exempt:"


def _violations(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _RAW_READ.search(line) and _EXEMPT not in line:
            out.append((lineno, line.strip()))
    return out


@pytest.mark.parametrize("filename", SCANNED_FILES)
def test_no_unmarked_raw_time_or_id_reads(filename: str) -> None:
    path = _SRC / filename
    violations = _violations(path)
    assert not violations, (
        f"Unmarked raw time/uuid reads in {filename} (route through Clock/"
        f"RunIdentity, or annotate '# det-exempt: <reason>'):\n"
        + "\n".join(f"  L{n}: {text}" for n, text in violations)
    )
