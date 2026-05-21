"""Make the shared ``support`` test package importable as ``support.*``.

Adds the ``tests/`` directory to ``sys.path`` so test modules can do
``from support.fakes import FakeClock`` without a ``tests`` package prefix.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
