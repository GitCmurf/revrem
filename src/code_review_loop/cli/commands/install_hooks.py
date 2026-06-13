"""``revrem install-hooks`` subcommand."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from code_review_loop import git_hooks
from code_review_loop.cli.args import parse_install_hooks_args

from ..outcome import CommandFailed, CommandOk

MANAGED_BEGIN = "# REVREM_MANAGED_HOOK: begin"
MANAGED_END = "# REVREM_MANAGED_HOOK: end"
HOOK_TYPES = ("pre-commit", "pre-push")


@dataclass(frozen=True)
class HookAction:
    hook: str
    status: str
    path: str
    backup_path: str | None = None
    message: str = ""


def main(argv: Sequence[str]) -> int:
    args = parse_install_hooks_args(argv)
    cwd = Path(args.cwd) if args.cwd is not None else Path.cwd()
    output_format = args.format or ("text" if sys.stdout.isatty() else "json")
    try:
        actions = (
            uninstall_hooks(cwd, _selected_hook_types(args.type))
            if args.uninstall
            else install_hooks(cwd, _selected_hook_types(args.type), force=args.force)
        )
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code

    if output_format == "json":
        print(json.dumps([asdict(action) for action in actions], indent=2, sort_keys=True))
    else:
        for action in actions:
            suffix = f" backup={action.backup_path}" if action.backup_path else ""
            print(f"{action.hook}: {action.status} {action.path}{suffix}")
            if action.message:
                print(f"  {action.message}")
    return CommandOk().exit_code


def install_hooks(cwd: Path, hook_types: Sequence[str], *, force: bool) -> list[HookAction]:
    hooks_dir = _hooks_dir(cwd)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    actions: list[HookAction] = []
    for hook_type in hook_types:
        path = hooks_dir / hook_type
        backup_path: Path | None = None
        if _hook_path_exists(path) and not _is_managed(path):
            if not force:
                raise OSError(
                    f"{path} already exists and is not RevRem-managed; rerun with --force "
                    "to back it up and replace it"
                )
            backup_path = _next_backup_path(path)
            path.rename(backup_path)
        path.write_text(_hook_template(hook_type), encoding="utf-8")
        path.chmod(path.stat().st_mode | 0o755)
        actions.append(
            HookAction(
                hook=hook_type,
                status="installed",
                path=str(path),
                backup_path=str(backup_path) if backup_path is not None else None,
                message="RevRem-managed hook installed with bounded defaults.",
            )
        )
    return actions


def uninstall_hooks(cwd: Path, hook_types: Sequence[str]) -> list[HookAction]:
    hooks_dir = _hooks_dir(cwd)
    actions: list[HookAction] = []
    for hook_type in hook_types:
        path = hooks_dir / hook_type
        if not _hook_path_exists(path):
            actions.append(HookAction(hook=hook_type, status="absent", path=str(path)))
            continue
        if not _is_managed(path):
            actions.append(
                HookAction(
                    hook=hook_type,
                    status="skipped",
                    path=str(path),
                    message="Existing hook is not RevRem-managed.",
                )
            )
            continue
        path.unlink()
        actions.append(
            HookAction(
                hook=hook_type,
                status="removed",
                path=str(path),
                message="Removed RevRem-managed hook.",
            )
        )
    return actions


def _selected_hook_types(value: str) -> tuple[str, ...]:
    return HOOK_TYPES if value == "all" else (value,)


def _hooks_dir(cwd: Path) -> Path:
    configured_hooks = git_hooks.configured_hooks_path(cwd)
    if configured_hooks is not None:
        return configured_hooks
    hooks = git_hooks.default_hooks_dir(cwd)
    if hooks is None:
        raise OSError(f"{cwd.resolve()} is not a Git repository or git is unavailable")
    return hooks


def _is_managed(path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    except UnicodeDecodeError:
        return False
    return MANAGED_BEGIN in text and MANAGED_END in text


def _hook_path_exists(path: Path) -> bool:
    # Treat broken symlinks as present so install-hooks never writes through them.
    return path.exists() or path.is_symlink()


def _next_backup_path(path: Path) -> Path:
    candidate = path.with_name(f"{path.name}.revrem-backup")
    if not _hook_path_exists(candidate):
        return candidate
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.revrem-backup.{index}")
        if not _hook_path_exists(candidate):
            return candidate
    raise OSError(f"could not choose a backup path for {path}")


def _hook_template(hook_type: str) -> str:
    return f"""#!/bin/sh
{MANAGED_BEGIN}
# Managed by `revrem install-hooks`; edit via environment variables or uninstall first.
set -eu

REVREM_BIN="${{REVREM_BIN:-revrem}}"
REVREM_BASE="${{REVREM_BASE:-main}}"
REVREM_MAX_ITERATIONS="${{REVREM_MAX_ITERATIONS:-1}}"
REVREM_MAX_WALL_SECONDS="${{REVREM_MAX_WALL_SECONDS:-900}}"
REVREM_MAX_TOKENS="${{REVREM_MAX_TOKENS:-200000}}"
REVREM_MAX_USD="${{REVREM_MAX_USD:-1.00}}"

export REVREM_HOOK_TYPE="{hook_type}"
exec "$REVREM_BIN" \\
  --base "$REVREM_BASE" \\
  --max-iterations "$REVREM_MAX_ITERATIONS" \\
  --max-wall-seconds "$REVREM_MAX_WALL_SECONDS" \\
  --max-tokens "$REVREM_MAX_TOKENS" \\
  --max-usd "$REVREM_MAX_USD" \\
  --summary-format text
{MANAGED_END}
"""
