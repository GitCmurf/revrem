"""Snapshot normalizer for the machine-contract golden masters (REVREM-TASK-003 C6/A2).

Canonicalizes the nondeterminism that survives the Clock/RunIdentity seam so a
committed snapshot is stable across machines and runs. Scope is deliberately
minimal — only the canonicalizations the current golden snapshots actually
exercise (A2a: run-directory paths and budget wall-time). New placeholders
(git SHAs, byte sizes, ...) are added in A2b alongside their first real
consumer, not speculatively.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CWD_PLACEHOLDER = "<RUN_DIR>"
DURATION_PLACEHOLDER = "<DURATION>"
CLI_VERSION_PLACEHOLDER = "<CLI_VERSION>"

# Numeric keys holding a measured wall-clock duration (real monotonic time that
# the A1 seam intentionally does not inject — see the behaviour ledger).
_DURATION_KEYS = frozenset({"wall_elapsed_seconds"})

# String keys holding the RevRem CLI version, which changes every release and is
# metadata rather than behaviour — canonicalize it so the golden masters stay
# stable across version bumps.
_CLI_VERSION_KEYS = frozenset({"cli_version"})


def normalize(value: Any, *, run_dir: Path | str) -> Any:
    """Return a deep copy of ``value`` with volatile fields canonicalized.

    - any string containing ``run_dir`` has that prefix replaced with
      ``<RUN_DIR>`` (absolute temp paths in artifact locations);
    - any ``wall_elapsed_seconds`` number becomes ``<DURATION>``.
    """
    run_dir_str = str(run_dir)

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: _walk_value(key, val) for key, val in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, str):
            return node.replace(run_dir_str, CWD_PLACEHOLDER)
        return node

    def _walk_value(key: str, val: Any) -> Any:
        if key in _DURATION_KEYS and isinstance(val, (int, float)) and not isinstance(val, bool):
            return DURATION_PLACEHOLDER
        if key in _CLI_VERSION_KEYS and isinstance(val, str):
            return CLI_VERSION_PLACEHOLDER
        return _walk(val)

    return _walk(value)
