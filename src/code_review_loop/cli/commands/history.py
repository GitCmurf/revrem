"""``revrem history`` subcommand (REVREM-TASK-003 Wave C1a)."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from code_review_loop import run_history

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    from code_review_loop import loop as _cli  # late import; preserves monkeypatching

    args = _cli.parse_history_args(argv)
    try:
        output_format = getattr(args, "format", None) or "text"
        if args.command == "list":
            if args.limit < 1:
                raise ValueError("--limit must be at least 1")
            records = run_history.read_history(limit=args.limit)
            if output_format == "json":
                print(json.dumps(records, indent=2, sort_keys=True))
            else:
                if not records:
                    print("No RevRem run history found.")
                    return CommandOk().exit_code
                for record in records:
                    run_id = record.get("run_id") or "<unknown>"
                    status = record.get("final_status") or "unknown"
                    reason = record.get("stopped_reason") or "unknown"
                    base = record.get("base") or "unknown"
                    artifact_dir = record.get("artifact_dir") or ""
                    print(f"{run_id} {status} ({reason}) base={base} artifacts={artifact_dir}")
            return CommandOk().exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    raise AssertionError(f"unhandled history command: {args.command}")
