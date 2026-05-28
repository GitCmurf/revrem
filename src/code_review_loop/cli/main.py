"""Top-level CLI entrypoint and subcommand dispatch."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop.cli.args import parse_args
from code_review_loop.cli.commands.profile import save_profile_from_args
from code_review_loop.cli.config_builder import build_loop_config
from code_review_loop.cli.exit import map_application_call


def main(argv: Sequence[str] | None = None) -> int:
    from code_review_loop import application
    from code_review_loop.cli.commands.registry import build_subcommand_registry

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv:
        handler = build_subcommand_registry().get(raw_argv[0])
        if handler is not None:
            return handler(raw_argv[1:])

    args = parse_args(raw_argv)
    try:
        config, summary_format = build_loop_config(args, Path.cwd())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1  # outcome-exempt: configuration failed before RunOutcome exists
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1  # outcome-exempt: configuration failed before RunOutcome exists

    if args.save_profile:
        return save_profile_from_args(
            args,
            config,
            summary_format=summary_format,
            cwd=Path.cwd(),
        )

    app_exit = map_application_call(lambda: application.run_review_loop(config))
    summary = app_exit.summary
    if app_exit.error:
        if not args.dry_run and not args.no_run_history and summary.get("run_id"):
            try:
                application.append_run_history(summary, config)
            except OSError as history_exc:
                print(f"WARNING: could not write run history: {history_exc}", file=sys.stderr)
        if app_exit.cancelled:
            print(app_exit.error, file=sys.stderr)
        else:
            print(f"ERROR: {app_exit.error}", file=sys.stderr)
        return app_exit.exit_code

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
        return 0  # outcome-exempt: dry-run summary is intentionally non-terminal
    return app_exit.exit_code
