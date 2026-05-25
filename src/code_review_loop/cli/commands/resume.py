"""``revrem resume`` subcommand."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import application, diagnostics, resume
from code_review_loop.cli.args import parse_resume_args
from code_review_loop.core.outcome import outcome_to_exit_code
from code_review_loop.runtime import RunLoopFailed, format_terminal_summary

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
    try:
        summary = application.resume_review_loop(run_dir, cwd=Path.cwd())
    except RunLoopFailed as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        code = outcome_to_exit_code(exc.outcome) if exc.outcome is not None else 1
        return CommandFailed(exit_code=code).exit_code
    except KeyboardInterrupt:
        print("Cancelled by user.", file=sys.stderr)
        return CommandFailed(exit_code=5).exit_code
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=4).exit_code
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(format_terminal_summary(summary))
    if summary.get("final_status") == "clear":
        return CommandOk().exit_code
    return CommandFailed(exit_code=2).exit_code
