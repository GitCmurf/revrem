"""Monkeypatch burn-down ratchet (REVREM-TASK-003 Contract C2).

The God-object refactor retires the practice of reaching into
``code_review_loop.cli`` internals via ``monkeypatch.setattr(MODULE, ...)``.
This test prevents *new* such call-sites from being added: it counts the
occurrences across the test suite and fails if the count exceeds the committed
baseline.

Two distinct metrics (do not conflate — see C2):
- *call-sites* (this ratchet): every ``monkeypatch.setattr(MODULE, ...)``.
- *distinct symbols* (burn-down narrative, tracked in PR bodies): 18 today.

As phases become ports the call-sites are deleted; when they drop, lower
``BASELINE`` to the new count so the ratchet keeps tightening. The end state
(Wave C3) is 0.

Burn-down log:
  57 — REVREM-TASK-003 baseline (Wave A complete)
  56 — B2c CommitHarness: migrate test_budget_exceeded_propagates_through_commit
  55 — B2d RemediationHarness: migrate test_budget_exceeded_propagates_through_remediation
  54 — B2e TriageHarness: migrate test_budget_exceeded_propagates_through_triage
  53 — B2f ReviewHarness: migrate test_live_cli_preflight_blocks_before_review_invocation
"""

from __future__ import annotations

import re
from pathlib import Path

# Committed baseline: measured call-site count of ``monkeypatch.setattr(MODULE, ...)``
# across tests/ at the start of REVREM-TASK-003. Ratchets downward only.
BASELINE = 53

_TESTS_DIR = Path(__file__).parent
_PATTERN = re.compile(r"monkeypatch\.setattr\(MODULE,")


def _count_module_patch_sites() -> int:
    total = 0
    for path in _TESTS_DIR.glob("*.py"):
        if path.name == Path(__file__).name:
            continue
        total += len(_PATTERN.findall(path.read_text(encoding="utf-8")))
    return total


def test_module_monkeypatch_count_does_not_increase() -> None:
    count = _count_module_patch_sites()
    assert count <= BASELINE, (
        f"New monkeypatch.setattr(MODULE, ...) call-sites detected: {count} > "
        f"baseline {BASELINE}. The refactor retires these via fake ports / "
        f"value-based tests (C2); do not add new ones."
    )


def test_baseline_is_not_stale() -> None:
    """If the real count has dropped below BASELINE, tighten the ratchet."""
    count = _count_module_patch_sites()
    assert count == BASELINE, (
        f"monkeypatch.setattr(MODULE, ...) call-sites dropped to {count}; "
        f"lower BASELINE from {BASELINE} to {count} to keep the ratchet tight."
    )
