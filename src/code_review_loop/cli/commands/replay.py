"""``revrem replay`` subcommand (REVREM-TASK-003 Wave C1a).

Replays a RevRem run from ``events.jsonl`` without invoking a model.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import events
from code_review_loop.cli.args import parse_replay_args

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_replay_args(argv)
    path = Path(args.run_dir) / events.EVENTS_FILENAME
    try:
        records, truncated = events.read_events(path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    print(events.render_compact(records), end="")
    # Replay's "truncated stream" signal historically used exit code 1; keep
    # the contract by mapping it to CommandFailed without altering the value.
    if truncated:
        return CommandFailed(exit_code=1).exit_code
    return CommandOk().exit_code
