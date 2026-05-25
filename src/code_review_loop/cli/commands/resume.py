"""``revrem resume`` subcommand (REVREM-TASK-003 Wave C1a).

The resume preconditions, ``run_loop`` invocation, and 11+ ``_resume_*``
helpers (`resume_precondition_issues`, `resume_run`, `latest_resume_review_path`,
``format_terminal_summary``, ``outcome_to_exit_code``, the ``RunLoopFailed``
exception, etc.) remain in ``code_review_loop.cli`` for C1a and are looked up
lazily so existing ``monkeypatch.setattr(MODULE, …)`` test patches against
``run_loop`` and the resume helpers stay in effect.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import diagnostics
from code_review_loop.core.outcome import outcome_to_exit_code

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    from code_review_loop import loop as _cli  # late import; preserves monkeypatching

    args = _cli.parse_resume_args(argv)
    run_dir = Path(args.run_dir)
    try:
        issues = _cli.resume_precondition_issues(run_dir, cwd=Path.cwd())
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
        summary = _cli.resume_run(run_dir)
    except _cli.RunLoopFailed as exc:
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
        print(_cli.format_terminal_summary(summary))
    if summary.get("final_status") == "clear":
        return CommandOk().exit_code
    return CommandFailed(exit_code=2).exit_code
