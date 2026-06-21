"""Loader for the finished-run fixture catalogue (REVREM-PLAN-005 T0).

Each entry under ``tests/fixtures/runs/<scenario>/`` is a co-located run
directory containing both ``summary.json`` and ``events.jsonl`` — the two
inputs the read-only consumers in v0.5.0 (``revrem report``, the GitHub
Action) read from a finished run. The catalogue is shared input material
so later tasks are pure feature work; ``load_run`` lets a test address a
scenario by stable name without hard-coding paths.

Scenarios mirror the run-loop terminal states the report must render:
``clear``, ``findings_remediated``, ``findings_remaining``, ``timeout``,
``check_failure``, ``cost_ceiling``, ``cancelled``, ``all_suppressed``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "runs"

# The canonical scenario names. Asserted by the fixture meta-test so a
# typo or a stray directory is caught immediately rather than producing a
# confusing "file not found" in a downstream report test.
RUN_SCENARIOS: tuple[str, ...] = (
    "clear",
    "findings_remediated",
    "findings_remaining",
    "timeout",
    "check_failure",
    "cost_ceiling",
    "cancelled",
    "all_suppressed",
)


def load_run(name: str) -> Path:
    """Return the run-directory ``Path`` for scenario ``name``.

    Asserts the directory and both expected files exist so callers can use
    the result directly without re-checking.
    """
    if name not in RUN_SCENARIOS:
        raise KeyError(
            f"unknown run fixture {name!r}; known: {', '.join(RUN_SCENARIOS)}"
        )
    run_dir = RUN_FIXTURE_DIR / name
    summary = run_dir / "summary.json"
    events = run_dir / "events.jsonl"
    assert run_dir.is_dir(), f"run fixture directory missing: {run_dir}"
    assert summary.is_file(), f"run fixture missing summary.json: {run_dir}"
    assert events.is_file(), f"run fixture missing events.jsonl: {run_dir}"
    return run_dir
