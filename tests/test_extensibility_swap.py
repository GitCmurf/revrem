from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from code_review_loop.core.outcome import OutcomeClear
from code_review_loop.core.ports import (
    CommandResult,
    ReviewOutcome,
    ReviewRequest,
    ReviewStatus,
    RunContext,
)
from tests.support.headless import HeadlessRun, SequencedChecksHarness


class PolicyReviewHarness:
    """Review harness with behavior, not just canned status data."""

    def __init__(self, *, clear_after_iteration: int) -> None:
        self.clear_after_iteration = clear_after_iteration
        self.calls: list[ReviewRequest] = []

    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        self.calls.append(request)
        label = request.display_label or request.artifact_label
        iteration = int(label) if label.isdigit() else self.clear_after_iteration
        status: ReviewStatus = "clear" if iteration >= self.clear_after_iteration else "findings"
        return ReviewOutcome(
            status=status,
            result=CommandResult(
                ["policy", "review"],
                0,
                stdout=f"policy status: {status}\nREVIEW_STATUS: {status}\n",
            ),
        )


def test_review_behavior_can_change_through_injected_harness(tmp_path: Path) -> None:
    review = PolicyReviewHarness(clear_after_iteration=4)
    run = HeadlessRun.with_tmp_config(
        tmp_path,
        review=review,
        checks=SequencedChecksHarness([(), (), ()]),
    )
    run.config = replace(run.config, max_iterations=4)

    result = run.run()

    assert isinstance(result.outcome, OutcomeClear)
    assert [request.display_label for request in review.calls] == ["1", "2", "3", "4"]
    assert result.to_dict()["iterations"][-1]["iteration"] == 4
