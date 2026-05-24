"""``revrem config`` subcommand (REVREM-TASK-003 Wave C1a).

Manages user/project profile configuration. Profile helpers
(``edit_profile_config``, ``new_profile_from_args``, ``_format_profile_list_item``)
remain in ``code_review_loop.cli`` for C1a and are looked up lazily so existing
``monkeypatch.setattr(MODULE, …)`` test patches stay in effect.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

from code_review_loop import profiles

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    from code_review_loop import cli as _cli  # late import; preserves monkeypatching

    args = _cli.parse_config_args(argv)
    try:
        output_format = getattr(args, "format", None)
        if args.command == "list":
            items = profiles.profile_list_items(cwd=Path.cwd())
            if (output_format or "text") == "json":
                print(
                    json.dumps(
                        [profiles.profile_list_item_to_dict(item) for item in items],
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                for item in items:
                    print(_cli._format_profile_list_item(item))
            return CommandOk().exit_code
        if args.command == "show":
            if output_format == "text":
                print(
                    "ERROR: 'text' format is not supported for 'show'. Use 'toml' or 'json'.",
                    file=sys.stderr,
                )
                return CommandFailed(exit_code=1).exit_code
            profile = profiles.resolve_profile(
                args.name,
                cwd=Path.cwd(),
                require_implemented=False,
            )
            if (output_format or "toml") == "json":
                print(profiles.profile_to_json(profile), end="")
            else:
                print(profiles.profile_to_toml(profile), end="")
            return CommandOk().exit_code
        if args.command == "new":
            profile = _cli.new_profile_from_args(args)
            path = profiles.write_user_profile(profile, force=args.force)
            print(f"created {args.name} in {path}")
            return CommandOk().exit_code
        if args.command == "edit":
            path = _cli.edit_profile_config(args.name, cwd=Path.cwd())
            print(f"edited {args.name} in {path}")
            return CommandOk().exit_code
        if args.command == "clone":
            path = profiles.clone_user_profile(
                args.source,
                args.target,
                cwd=Path.cwd(),
                force=args.force,
            )
            print(f"cloned {args.source} to {args.target} in {path}")
            return CommandOk().exit_code
        if args.command == "delete":
            if not args.yes:
                print("ERROR: pass --yes to delete a profile non-interactively", file=sys.stderr)
                return CommandFailed(exit_code=1).exit_code
            path = profiles.delete_user_profile(args.name)
            print(f"deleted {args.name} from {path}")
            return CommandOk().exit_code
        if args.command == "export":
            profile = profiles.resolve_profile(
                args.name,
                cwd=Path.cwd(),
                require_implemented=False,
            )
            print(profiles.profile_to_toml(profile, include_wrapper=True), end="")
            return CommandOk().exit_code
        if args.command == "import":
            path = profiles.import_user_profiles(Path(args.path), force=args.force)
            print(f"imported profiles into {path}")
            return CommandOk().exit_code
        if args.command == "doctor":
            profile_names = [item.name for item in profiles.list_profiles(cwd=Path.cwd())]
            info: dict[str, object] = {
                "user_config": str(profiles.user_config_path()),
                "project_config": str(profiles.project_config_path(Path.cwd())),
                "profiles": profile_names,
            }
            if args.profile:
                info["resolved_profile"] = profiles.profile_to_dict(
                    profiles.resolve_profile(
                        args.profile,
                        cwd=Path.cwd(),
                        require_implemented=False,
                    )
                )
            if (output_format or "text") == "json":
                print(json.dumps(info, indent=2, sort_keys=True))
            else:
                print(f"user_config: {info['user_config']}")
                print(f"project_config: {info['project_config']}")
                print("profiles: " + ", ".join(profile_names))
                if "resolved_profile" in info:
                    print(f"resolved_profile: {json.dumps(info['resolved_profile'], indent=2)}")
            return CommandOk().exit_code
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    raise AssertionError(f"unhandled config command: {args.command}")
