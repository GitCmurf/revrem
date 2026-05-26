"""``revrem config`` subcommand."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import profiles
from code_review_loop.cli.args import parse_config_args
from code_review_loop.cli.config_builder import new_profile_from_args

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_config_args(argv)
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
                    print(_format_profile_list_item(item))
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
            profile = new_profile_from_args(args)
            path = profiles.write_user_profile(profile, force=args.force)
            print(f"created {args.name} in {path}")
            return CommandOk().exit_code
        if args.command == "edit":
            path = edit_profile_config(args.name, cwd=Path.cwd())
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


def _format_profile_list_item(item: profiles.ProfileListItem) -> str:
    desc = f" - {item.description}" if item.description else ""
    details: list[str] = []
    if item.source:
        details.append(item.source)
    details.append(f"last used {item.last_used_at or 'never'}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"{item.name}{desc}{suffix}"


def edit_profile_config(name: str, *, cwd: Path, home: Path | None = None) -> Path:
    path = _profile_config_owner_path(name, cwd, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    command = _editor_command() + [str(path)]
    try:
        subprocess.run(command, cwd=path.parent, check=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"editor not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"editor exited with status {exc.returncode}") from exc
    return path


def _profile_config_owner_path(name: str, cwd: Path, home: Path | None = None) -> Path:
    project_path = profiles.project_config_path(cwd)
    project_file = profiles.load_profile_file(project_path)
    if name in project_file.profiles:
        return project_path

    user_path = profiles.user_config_path(home)
    user_file = profiles.load_profile_file(user_path)
    if name in user_file.profiles:
        return user_path

    raise FileNotFoundError(f"profile not found: {name}")


def _editor_command() -> list[str]:
    editor = os.environ.get("EDITOR", "").strip()
    if not editor:
        raise RuntimeError("EDITOR is not set; cannot open a config editor")
    command = shlex.split(editor, posix=os.name != "nt")
    if os.name == "nt":
        command = [part.strip('"') for part in command]
    if not command:
        raise RuntimeError("EDITOR is empty; cannot open a config editor")
    return command
