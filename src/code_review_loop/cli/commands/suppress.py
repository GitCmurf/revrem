"""``revrem suppress`` subcommand (REVREM-TASK-003 Wave C1a).

Manages explicit finding suppressions.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from code_review_loop import suppressions
from code_review_loop.cli.args import parse_suppress_args

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_suppress_args(argv)
    path = _suppression_path_for_scope(args.scope, Path.cwd())
    audit_path = _suppression_audit_path_for_scope(args.scope, Path.cwd())
    try:
        if args.command == "add":
            entry = suppressions.make_entry(
                fingerprint=args.fingerprint,
                summary=args.summary,
                rationale=args.rationale,
                severity=args.severity,
                scope=args.scope,
                expires_at=args.expires,
                critical_override=args.critical_override,
                created_by=args.created_by,
            )
            suppressions.add_entry(path, entry, audit_path=audit_path)
            print(f"added {entry.fingerprint} to {path}")
            return CommandOk().exit_code
        if args.command == "remove":
            if not suppressions.remove_entry(path, args.fingerprint, audit_path=audit_path):
                print(f"ERROR: suppression not found: {args.fingerprint}", file=sys.stderr)
                return CommandFailed(exit_code=2).exit_code
            print(f"removed {args.fingerprint} from {path}")
            return CommandOk().exit_code
        if args.command == "expire":
            count = suppressions.expire_entries(path, audit_path=audit_path)
            print(f"expired {count} suppression(s) from {path}")
            return CommandOk().exit_code
        if args.command == "check":
            matches = suppressions.load_effective_suppressions(Path.cwd())
            match = matches.get(args.fingerprint)
            if match is None:
                return CommandFailed(exit_code=2).exit_code
            if args.format == "json":
                print(json.dumps(asdict(match.entry), indent=2, sort_keys=True))
            else:
                print(f"suppressed {args.fingerprint} via {match.source_path}")
            return CommandOk().exit_code
        if args.command == "list":
            entries = suppressions.load_entries(path)
            if args.format == "json":
                print(json.dumps([asdict(entry) for entry in entries], indent=2, sort_keys=True))
            else:
                for entry in entries:
                    expires = f" expires={entry.expires_at}" if entry.expires_at else ""
                    print(f"{entry.fingerprint} {entry.severity_at_suppression} {entry.summary}{expires}")
            return CommandOk().exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    raise AssertionError(f"unhandled suppress command: {args.command}")


def _suppression_path_for_scope(scope: str, cwd: Path) -> Path:
    if scope == "repo":
        return suppressions.repo_suppressions_path(cwd)
    return suppressions.user_suppressions_path()


def _suppression_audit_path_for_scope(scope: str, cwd: Path) -> Path:
    if scope == "repo":
        return suppressions.repo_audit_path(cwd)
    return suppressions.user_audit_path()
