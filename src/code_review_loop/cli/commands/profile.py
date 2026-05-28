"""Profile helper commands reached from the top-level parser."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_review_loop import profiles
from code_review_loop.cli.config_builder import profile_from_loop_config
from code_review_loop.config import LoopConfig


def save_profile_from_args(
    args: Any,
    config: LoopConfig,
    *,
    summary_format: str,
    cwd: Path,
) -> int:
    """Persist the current loop configuration as a project profile."""

    profile = profile_from_loop_config(
        args.save_profile,
        config,
        summary_format=summary_format,
        description=f"Saved from RevRem CLI on {datetime.now(UTC).date().isoformat()}",
        include_artifact_dir=args.artifact_dir is not None,
        timeout_seconds=args.timeout_seconds,
    )
    try:
        path = profiles.write_project_profile(
            profile,
            cwd=cwd,
            force=args.save_profile_force,
        )
    except FileExistsError as exc:
        print(f"ERROR: {exc}; pass --save-profile-force to replace it", file=sys.stderr)
        return 1  # outcome-exempt: profile write failed before loop execution
    except OSError as exc:
        print(f"ERROR: could not save project profile: {exc}", file=sys.stderr)
        return 1  # outcome-exempt: profile write failed before loop execution
    print(f"saved {args.save_profile} in {path}")
    return 0  # outcome-exempt: profile save command does not run the loop
