"""``revrem completions`` subcommand."""

from __future__ import annotations

from collections.abc import Sequence

from code_review_loop.cli.args import parse_completions_args
from code_review_loop.cli.commands.registry import build_subcommand_registry

from ..outcome import CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_completions_args(argv)
    subcommands = sorted(build_subcommand_registry())
    if args.shell == "bash":
        print(_bash(subcommands))
    elif args.shell == "zsh":
        print(_zsh(subcommands))
    else:
        print(_fish(subcommands))
    return CommandOk().exit_code


def _bash(subcommands: list[str]) -> str:
    words = " ".join(subcommands)
    return f"""# revrem bash completion
_revrem_complete() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "{words}" -- "$cur") )
    return
  fi
  case "${{COMP_WORDS[1]}}" in
    report) COMPREPLY=( $(compgen -W "--output --format --no-redact --i-understand-the-risks" -- "$cur") ) ;;
    config) COMPREPLY=( $(compgen -W "list show new edit clone delete export import doctor --format" -- "$cur") ) ;;
    *) COMPREPLY=( $(compgen -W "--profile --base --check --max-iterations --no-tty --progress-style" -- "$cur") ) ;;
  esac
}}
complete -F _revrem_complete revrem
"""


def _zsh(subcommands: list[str]) -> str:
    words = " ".join(subcommands)
    return f"""#compdef revrem
_revrem() {{
  local -a subcommands
  subcommands=({words})
  if (( CURRENT == 2 )); then
    _describe 'subcommand' subcommands
  else
    _arguments '*: :((--profile --base --check --max-iterations --no-tty --progress-style --output --format))'
  fi
}}
_revrem "$@"
"""


def _fish(subcommands: list[str]) -> str:
    lines = ["# revrem fish completion"]
    for command in subcommands:
        lines.append(f"complete -c revrem -f -n '__fish_use_subcommand' -a {command}")
    for flag in ("profile", "base", "check", "max-iterations", "no-tty", "progress-style"):
        lines.append(f"complete -c revrem -l {flag}")
    return "\n".join(lines) + "\n"
