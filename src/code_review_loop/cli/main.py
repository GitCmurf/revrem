"""Top-level CLI entrypoint and subcommand dispatch."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from code_review_loop import profiles
from code_review_loop.cli.args import parse_args
from code_review_loop.cli.config_builder import (
    build_loop_config,
    profile_from_loop_config,
)
from code_review_loop.cli.outcome import summary_from_result
from code_review_loop.core.outcome import outcome_to_exit_code


def _build_subcommand_registry() -> dict[str, Callable[[Sequence[str]], int]]:
    from code_review_loop import tui as _tui
    from code_review_loop.cli.commands import (
        bundle,
        config,
        doctor,
        history,
        policy,
        replay,
        resume,
        suppress,
        triage,
    )

    return {
        "bundle-bug-report": bundle.main,
        "config": config.main,
        "doctor": doctor.main,
        "history": history.main,
        "policy": policy.main,
        "preflight": doctor.main,
        "replay": replay.main,
        "resume": resume.main,
        "suppress": suppress.main,
        "triage": triage.main,
        "ui": _tui.main,
    }


def main(argv: Sequence[str] | None = None) -> int:
    from code_review_loop import application

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv:
        handler = _build_subcommand_registry().get(raw_argv[0])
        if handler is not None:
            return handler(raw_argv[1:])

    args = parse_args(raw_argv)
    try:
        config, summary_format = build_loop_config(args, Path.cwd())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.save_profile:
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
                cwd=Path.cwd(),
                force=args.save_profile_force,
            )
        except FileExistsError as exc:
            print(f"ERROR: {exc}; pass --save-profile-force to replace it", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"ERROR: could not save project profile: {exc}", file=sys.stderr)
            return 1
        print(f"saved {args.save_profile} in {path}")
        return 0

    try:
        result = application.run_review_loop(config)
        summary = summary_from_result(result)
    except application.RunLoopFailed as exc:
        summary = exc.summary
        if not args.dry_run and not args.no_run_history and summary.get("run_id"):
            try:
                application.append_run_history(summary, config)
            except OSError as history_exc:
                print(f"WARNING: could not write run history: {history_exc}", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return outcome_to_exit_code(exc.outcome) if exc.outcome is not None else 1
    except KeyboardInterrupt:
        print("Cancelled by user.", file=sys.stderr)
        return 5
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.dry_run and not args.no_run_history and summary.get("run_id"):
        try:
            application.append_run_history(summary, config)
        except OSError as exc:
            print(f"WARNING: could not write run history: {exc}", file=sys.stderr)

    if summary_format in {"text", "both"}:
        print(application.format_terminal_summary(summary))
    if summary_format in {"json", "both"}:
        if summary_format == "both":
            print()
        print(json.dumps(summary, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    return 0 if summary.get("final_status") == "clear" else 2
