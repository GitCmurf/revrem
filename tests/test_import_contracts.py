"""Run the import-linter contracts as part of the test gate (REVREM-TASK-003 C4).

Wave A0 ships a placeholder contract (domain leaf modules must not import the
cli God object). The full layered core/adapters/cli dependency rule replaces it
in Wave B0. Running ``lint-imports`` here makes the contract machine-enforced by
the existing pytest gate (locally via the pre-commit pytest hook and in CI),
not merely "available".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _lint_imports_executable() -> Path | None:
    candidate = Path(sys.executable).parent / "lint-imports"
    return candidate if candidate.exists() else None


def test_import_linter_contracts_are_kept() -> None:
    executable = _lint_imports_executable()
    if executable is None:
        pytest.skip("import-linter not installed in this environment")
    result = subprocess.run(
        [str(executable)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"import-linter contracts broken (C4):\n{result.stdout}\n{result.stderr}"
    )
