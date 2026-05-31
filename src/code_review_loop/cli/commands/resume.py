"""``revrem resume`` subcommand."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import application, diagnostics, resume
from code_review_loop.cli.args import parse_resume_args
from code_review_loop.cli.exit import map_application_call
from code_review_loop.runtime import format_terminal_summary

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_resume_args(argv)
    run_dir = Path(args.run_dir)
    try:
        issues = resume.resume_precondition_issues(run_dir, cwd=Path.cwd())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=4).exit_code
    if args.format == "json":
        print(diagnostics.doctor_json(issues), end="")
        if diagnostics.has_blocking_issue(issues):
            return CommandFailed(exit_code=4).exit_code
    else:
        print(diagnostics.doctor_text(issues), end="")
        if diagnostics.has_blocking_issue(issues):
            return CommandFailed(exit_code=4).exit_code
    app_exit = map_application_call(
        lambda: application.resume_review_loop(run_dir, cwd=Path.cwd()),
        expected_errors=(OSError, ValueError),
        expected_error_exit_code=4,
    )
    if app_exit.error:
        if app_exit.cancelled:
            print(app_exit.error, file=sys.stderr)
        else:
            print(f"ERROR: {app_exit.error}", file=sys.stderr)
        return CommandFailed(exit_code=app_exit.exit_code).exit_code
    summary = app_exit.summary
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(format_terminal_summary(summary))
    exit_code = app_exit.exit_code
    if exit_code == CommandOk().exit_code:
        return CommandOk().exit_code
    return CommandFailed(exit_code=exit_code).exit_code
