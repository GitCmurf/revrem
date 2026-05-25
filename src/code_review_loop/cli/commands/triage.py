"""``revrem triage`` subcommand (REVREM-TASK-003 Wave C1a)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    from code_review_loop import cli as _cli  # late import; preserves monkeypatching

    args = _cli.parse_triage_args(argv)
    try:
        if args.command == "explain":
            code = _cli.triage_explain(
                Path(args.run_dir),
                args.iteration,
                output_format=getattr(args, "format", None),
            )
            return CommandOk(exit_code=code).exit_code if code == 0 else CommandFailed(exit_code=code).exit_code
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    return CommandOk().exit_code
