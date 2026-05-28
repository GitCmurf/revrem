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

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "code_review_loop"

# Dependency-free core files. These must stay value-only: no raw time/id,
# subprocess, environment, random, or filesystem access.
CORE_SCANNED_FILES = tuple(
    sorted(
        path.relative_to(_SRC).as_posix()
        for path in (_SRC / "core").glob("*.py")
        if path.name != "__init__.py"
    )
)

# Imperative-shell files whose raw time/id reads feed the machine contract.
SHELL_SCANNED_FILES = (
    "events.py",
    "runner.py",
    "runner_shell.py",
    "runner_setup.py",
    "runner_finish.py",
    "routing_artifacts.py",
)

_RAW_READ = re.compile(r"datetime\.now|datetime\.utcnow|time\.monotonic|uuid\.uuid4")
_CORE_FORBIDDEN = re.compile(
    r"datetime\.now|datetime\.utcnow|time\.monotonic|time\.time|uuid\.uuid4|"
    r"\brandom\.|os\.urandom|subprocess\.|os\.environ|os\.getenv|"
    r"\.read_text\(|\.write_text\(|\.open\(|\.exists\(|\.is_file\(|\.iterdir\(|\.glob\("
)
_EXEMPT = "det-exempt:"


def _violations(path: Path, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if pattern.search(line) and _EXEMPT not in line:
            out.append((lineno, line.strip()))
    return out


def test_core_determinism_gate_scans_engine_module() -> None:
    assert "core/engine.py" in CORE_SCANNED_FILES
    assert "cli/__init__.py" not in CORE_SCANNED_FILES
    assert "cli/__init__.py" not in SHELL_SCANNED_FILES


@pytest.mark.parametrize("filename", CORE_SCANNED_FILES)
def test_core_has_no_unmarked_nondeterminism_or_io(filename: str) -> None:
    path = _SRC / filename
    violations = _violations(path, _CORE_FORBIDDEN)
    assert not violations, (
        f"Unmarked nondeterminism or I/O in {filename} (keep core value-only, "
        f"or annotate '# det-exempt: <reason>'):\n"
        + "\n".join(f"  L{n}: {text}" for n, text in violations)
    )


@pytest.mark.parametrize("filename", SHELL_SCANNED_FILES)
def test_machine_contract_shell_has_no_unmarked_raw_time_or_id_reads(filename: str) -> None:
    path = _SRC / filename
    violations = _violations(path, _RAW_READ)
    assert not violations, (
        f"Unmarked raw time/uuid reads in {filename} (route through Clock/"
        f"RunIdentity, or annotate '# det-exempt: <reason>'):\n"
        + "\n".join(f"  L{n}: {text}" for n, text in violations)
    )
