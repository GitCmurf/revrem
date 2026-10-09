"""Effective model catalog command."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from code_review_loop.cli.args import parse_models_args
from code_review_loop.cli.outcome import CommandFailed, CommandOk
from code_review_loop.model_catalog import load_catalog


def main(argv: Sequence[str]) -> int:
    args = parse_models_args(argv)
    try:
        harness = None if args.all else (args.harness or "codex")
        rows = [asdict(item) for item in load_catalog(Path.cwd()).models_for(harness)]
        if args.format == "json":
            print(json.dumps(rows, indent=2, sort_keys=True))
        elif not rows:
            print("No matching catalog models.")
        else:
            print("HARNESS  MODEL            DEFAULT  EFFORTS")
            for row in rows:
                efforts = ",".join(row["efforts"]) or "provider-defined"
                print(f"{row['harness']:<8} {row['id']:<16} {row['default_effort'] or '-':<8} {efforts}")
        return CommandOk().exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
