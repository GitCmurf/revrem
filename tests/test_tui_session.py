from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import profiles
from code_review_loop.tui_session import LoopSession, PendingReviewSelection


def _profile(tmp_path: Path) -> profiles.Profile:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".revrem.toml").write_text(
        "[profiles.docs]\n"
        "[profiles.docs.pipeline]\nbase='main'\n"
        "[profiles.docs.review]\nharness='codex'\nmodel='gpt-5.6-sol'\n",
        encoding="utf-8",
    )
    return profiles.resolve_profile("docs", cwd=tmp_path, require_implemented=False)


def test_session_compiles_selected_pending_review_as_run_only_arguments(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    review = tmp_path / ".revrem" / "runs" / "run" / "review-final.txt"
    review.parent.mkdir(parents=True)
    review.write_text("finding", encoding="utf-8")
    session = LoopSession(
        profile_name="docs",
        pending_review=PendingReviewSelection(
            path=review,
            run_dir=review.parent,
            final_status="findings",
            stopped_reason="max_iterations_reached",
            excerpt="finding",
        ),
    )

    plan = session.compile_launch_plan(profile, dry_run=False)

    assert plan.argv[:3] == ("revrem", "--profile", "docs")
    assert plan.argv[-4:] == (
        "--initial-review-file",
        str(review),
        "--initial-review-mode",
        "compatible",
    )
    fresh = session.toggle_pending_review().compile_launch_plan(profile, dry_run=False)
    assert "--initial-review-file" not in fresh.argv


def test_session_rejects_profile_split_brain(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    with pytest.raises(ValueError, match="active loop profile"):
        LoopSession(profile_name="security").compile_launch_plan(
            profile, dry_run=False
        )
