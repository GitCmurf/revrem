"""``revrem checks`` subcommand."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import check_suggestions
from code_review_loop.cli.args import parse_checks_args

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_checks_args(argv)
    try:
        if args.command == "suggest":
            cwd = Path(args.cwd) if args.cwd is not None else Path.cwd()
            output_format = args.format or ("text" if sys.stdout.isatty() else "json")
            if output_format == "json":
                print(json.dumps(check_suggestions.suggestions_payload(cwd), indent=2, sort_keys=True))
            else:
                print(check_suggestions.render_suggestions_text(cwd), end="")
            return CommandOk().exit_code
        raise ValueError(f"unhandled checks command: {args.command}")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
