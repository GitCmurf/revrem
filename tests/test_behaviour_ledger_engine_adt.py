from __future__ import annotations

from pathlib import Path

from code_review_loop.core import engine


def test_behaviour_ledger_covers_current_engine_adt() -> None:
    ledger = (
        Path(__file__).resolve().parents[1] / "docs" / "05-planning" / "behaviour-ledger-task-003.md"
    ).read_text(encoding="utf-8")

    expected_names = (
        engine.LoopStarted,
        engine.ReviewDone,
        engine.TriageDone,
        engine.RemediationDone,
        engine.ChecksDone,
        engine.CommitDone,
        engine.NoFinalReview,
        engine.Continue,
        engine.RunReview,
        engine.RunTriage,
        engine.RunRemediation,
        engine.RunChecks,
        engine.RunCommit,
        engine.RetryViaCommitHook,
        engine.Stop,
    )

    missing = [item.__name__ for item in expected_names if f"`{item.__name__}`" not in ledger]

    assert missing == []
