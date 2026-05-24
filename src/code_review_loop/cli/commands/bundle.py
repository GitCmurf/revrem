"""``revrem bundle-bug-report`` subcommand (REVREM-TASK-003 Wave C1a).

Creates a redacted, deterministic bug-report bundle from a RevRem run
directory.

Helpers retained in ``code_review_loop.cli`` (parent package) are looked up
lazily so existing ``monkeypatch.setattr(MODULE, …)`` test patches against
the legacy God-object module remain in effect until C2/C3 retire them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from code_review_loop import bug_bundle

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    from code_review_loop import cli as _cli  # late import; preserves monkeypatching

    args = _cli.parse_bundle_bug_report_args(argv)
    if args.no_redact and not args.i_understand_the_risks:
        print("ERROR: --no-redact requires --i-understand-the-risks", file=sys.stderr)
        return CommandFailed(exit_code=4).exit_code
    try:
        result = bug_bundle.create_bug_bundle(
            bug_bundle.BundleOptions(
                run_dir=Path(args.run_dir),
                output_path=Path(args.output) if args.output else None,
                include_raw_transcripts=args.include_raw_transcripts,
                redact=not args.no_redact,
            )
        )
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    print(str(result.output_path))
    return CommandOk().exit_code
