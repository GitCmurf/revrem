"""Top-level CLI entrypoint and subcommand dispatch."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from code_review_loop.cli.args import parse_args
from code_review_loop.cli.commands.profile import save_profile_from_args
from code_review_loop.cli.config_builder import build_loop_config
from code_review_loop.cli.exit import map_application_call


def main(argv: Sequence[str] | None = None) -> int:
    from code_review_loop import application
    from code_review_loop.cli.commands.registry import dispatch_or_none

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    dispatch_result = dispatch_or_none(raw_argv)
    if dispatch_result is not None:
        return dispatch_result

    args = parse_args(raw_argv)
    try:
        config, summary_format = build_loop_config(args, Path.cwd())
        config = replace(config, command_line=("revrem", *_redacted_argv(raw_argv)))
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


def _redacted_argv(argv: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False
    sensitive_flags = {"--commit-message-prompt", "--triage-prompt"}
    for item in argv:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if item in sensitive_flags:
            redacted.append(item)
            redact_next = True
            continue
        if any(item.startswith(f"{flag}=") for flag in sensitive_flags):
            flag, _sep, _value = item.partition("=")
            redacted.append(f"{flag}=<redacted>")
            continue
        redacted.append(item)
    return tuple(redacted)
