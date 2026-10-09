"""Single source of truth for the TUI's active loop and run-only inputs."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from code_review_loop import profiles, tui_state


@dataclass(frozen=True)
class PendingReviewSelection:
    path: Path
    run_dir: Path
    final_status: str | None
    stopped_reason: str | None
    excerpt: str
    compatible: bool = True
    selected: bool = True
    git_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class LoopSession:
    """Active profile, provenance, and ephemeral launch inputs.

    Profile edits remain owned by ``LoopEditModel`` and persist through its
    existing save interface.  This module owns the cross-widget state that must
    agree before a dry or live run is compiled.
    """

    profile_name: str | None
    origin_label: str | None = None
    pending_review: PendingReviewSelection | None = None

    def adopt_profile(
        self, profile_name: str, *, origin_label: str | None = None
    ) -> LoopSession:
        return replace(self, profile_name=profile_name, origin_label=origin_label)

    def toggle_pending_review(self) -> LoopSession:
        if self.pending_review is None:
            return self
        return replace(
            self,
            pending_review=replace(
                self.pending_review, selected=not self.pending_review.selected
            ),
        )

    def compile_launch_plan(
        self,
        profile: profiles.Profile,
        *,
        dry_run: bool,
        profile_snapshot: Path | None = None,
    ) -> tui_state.LaunchPlan:
        if self.profile_name is not None and profile.name != self.profile_name:
            raise ValueError(
                f"active loop profile is {self.profile_name!r}, not {profile.name!r}"
            )
        plan = tui_state.launch_plan(profile, dry_run=dry_run)
        if profile_snapshot is not None:
            argv = (*plan.argv, "--profile-snapshot", str(profile_snapshot))
            plan = replace(plan, argv=argv, shell_command=shlex.join(argv))
        pending = self.pending_review
        if pending is None or not pending.selected:
            return plan
        argv = (
            *plan.argv,
            "--initial-review-file",
            str(pending.path),
            "--initial-review-mode",
            "compatible" if pending.compatible else "stale",
        )
        return replace(plan, argv=argv, shell_command=shlex.join(argv))
