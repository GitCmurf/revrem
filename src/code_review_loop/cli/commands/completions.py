"""``revrem completions`` subcommand."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from code_review_loop.cli import args as cli_args
from code_review_loop.cli.args import RevRemArgumentParser, parse_completions_args
from code_review_loop.cli.commands.registry import build_subcommand_registry

from ..outcome import CommandOk


@dataclass(frozen=True)
class CompletionSpec:
    root_words: tuple[str, ...]
    command_words: dict[str, tuple[str, ...]]
    nested_words: dict[tuple[str, str], tuple[str, ...]]


def main(argv: Sequence[str]) -> int:
    args = parse_completions_args(argv)
    spec = _completion_spec()
    if args.shell == "bash":
        print(_bash(spec))
    elif args.shell == "zsh":
        print(_zsh(spec))
    else:
        print(_fish(spec))
    return CommandOk().exit_code


def _completion_spec() -> CompletionSpec:
    subcommands = sorted(build_subcommand_registry())
    root_words = _words((*subcommands, *_parser_options(cli_args.build_run_parser())))
    parser_builders = {
        "bundle-bug-report": cli_args.build_bundle_bug_report_parser,
        "checks": cli_args.build_checks_parser,
        "completions": cli_args.build_completions_parser,
        "config": cli_args.build_config_parser,
        "doctor": cli_args.build_doctor_parser,
        "history": cli_args.build_history_parser,
        "install-hooks": cli_args.build_install_hooks_parser,
        "policy": cli_args.build_policy_parser,
        "preflight": cli_args.build_doctor_parser,
        "replay": cli_args.build_replay_parser,
        "report": cli_args.build_report_parser,
        "resume": cli_args.build_resume_parser,
        "suppress": cli_args.build_suppress_parser,
        "triage": cli_args.build_triage_parser,
    }
    command_words: dict[str, tuple[str, ...]] = {}
    nested_words: dict[tuple[str, str], tuple[str, ...]] = {}
    for command, build_parser in parser_builders.items():
        parser = build_parser()
        nested = _subcommand_parsers(parser)
        command_words[command] = _words(
            (*nested, *_parser_options(parser), *_parser_positional_choices(parser))
        )
        for nested_command, nested_parser in nested.items():
            nested_words[(command, nested_command)] = _words(
                (*_parser_options(nested_parser), *_parser_positional_choices(nested_parser))
            )
    return CompletionSpec(root_words, command_words, nested_words)


def _words(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(items)))


def _parser_options(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    options: list[str] = []
    for action in parser._actions:
        options.extend(option for option in action.option_strings if option.startswith("-"))
    return tuple(options)


def _parser_positional_choices(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    choices: list[str] = []
    for action in parser._actions:
        if action.option_strings or action.choices is None:
            continue
        choices.extend(str(choice) for choice in action.choices)
    return tuple(choices)


def _subcommand_parsers(parser: argparse.ArgumentParser) -> dict[str, RevRemArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _join(words: Sequence[str]) -> str:
    return " ".join(words)


def _bash_case_entries(mapping: dict[str, tuple[str, ...]]) -> str:
    return "\n".join(
        f'    {key}) words="{_join(words)}" ;;' for key, words in sorted(mapping.items())
    )


def _bash_nested_case_entries(mapping: dict[tuple[str, str], tuple[str, ...]]) -> str:
    return "\n".join(
        f'    {command}:{nested}) words="{_join(words)}" ;;'
        for (command, nested), words in sorted(mapping.items())
    )


def _bash(spec: CompletionSpec) -> str:
    root_words = _join(spec.root_words)
    command_cases = _bash_case_entries(spec.command_words)
    nested_cases = _bash_nested_case_entries(spec.nested_words)
    return f"""# revrem bash completion
_revrem_complete() {{
  local cur command nested key words
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "{root_words}" -- "$cur") )
    return
  fi
  command="${{COMP_WORDS[1]}}"
  nested="${{COMP_WORDS[2]}}"
  words=""
  if [[ $COMP_CWORD -ge 3 ]]; then
    key="${{command}}:${{nested}}"
    case "$key" in
{nested_cases}
    esac
  fi
  if [[ -z "$words" ]]; then
    case "$command" in
{command_cases}
      *) words="{root_words}" ;;
    esac
  fi
  COMPREPLY=( $(compgen -W "$words" -- "$cur") )
}}
complete -F _revrem_complete revrem
"""


def _zsh(spec: CompletionSpec) -> str:
    root_words = " ".join(f'"{word}"' for word in spec.root_words)
    all_words = " ".join(
        f'"{word}"'
        for word in _words(
            tuple(spec.root_words)
            + tuple(word for words in spec.command_words.values() for word in words)
            + tuple(word for words in spec.nested_words.values() for word in words)
        )
    )
    return f"""#compdef revrem
_revrem() {{
  local -a root_words all_words
  root_words=({root_words})
  all_words=({all_words})
  if (( CURRENT == 2 )); then
    _describe 'revrem command or option' root_words
  else
    _describe 'revrem option' all_words
  fi
}}
_revrem "$@"
"""


def _fish(spec: CompletionSpec) -> str:
    lines = ["# revrem fish completion"]
    subcommands = [word for word in spec.root_words if not word.startswith("-")]
    for command in subcommands:
        lines.append(f"complete -c revrem -f -n '__fish_use_subcommand' -a {command}")
    for flag in (word[2:] for word in spec.root_words if word.startswith("--")):
        lines.append(f"complete -c revrem -l {flag}")
    for command, words in sorted(spec.command_words.items()):
        for word in words:
            if word.startswith("--"):
                lines.append(f"complete -c revrem -n '__fish_seen_subcommand_from {command}' -l {word[2:]}")
            elif not word.startswith("-"):
                lines.append(f"complete -c revrem -n '__fish_seen_subcommand_from {command}' -a {word}")
    return "\n".join(lines) + "\n"
