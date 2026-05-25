"""Runner/core-engine integration ratchets (REVREM-TASK-003 Wave C)."""

from __future__ import annotations

import re
from pathlib import Path


def test_runner_uses_core_engine_run_without_direct_decide_bridge() -> None:
    runner_source = (Path(__file__).resolve().parents[1] / "src" / "code_review_loop" / "runner.py").read_text(
        encoding="utf-8"
    )

    assert "run as run_engine" in runner_source
    assert "decide as decide_engine" not in runner_source
    assert "max_steps=1" not in runner_source
    assert "_CaptureEngineAction" not in runner_source
    assert not re.search(r"\bdecide\s*\(", runner_source)
