from __future__ import annotations

import pytest

from code_review_loop.cli import args as cli_args
from code_review_loop.cli.commands import completions


@pytest.mark.parametrize("shell", ("bash", "zsh", "fish"))
def test_completions_emit_known_subcommand_and_flags(shell: str, capsys):
    assert completions.main([shell]) == 0
    out = capsys.readouterr().out
    assert "report" in out
    assert "completions" in out
    assert "--profile" in out or "-l profile" in out
    assert "--no-tty" in out or "-l no-tty" in out


def test_completion_spec_uses_argparse_flags():
    spec = completions._completion_spec()
    run_options = {
        option
        for action in cli_args.build_run_parser()._actions
        for option in action.option_strings
        if option.startswith("--")
    }

    assert run_options <= set(spec.root_words)
    assert "--external-review-truncation-policy" in spec.root_words
    assert "--include-raw-transcripts" in spec.command_words["bundle-bug-report"]
    assert "--i-understand-the-risks" in spec.command_words["report"]


def test_completion_spec_includes_nested_config_flags_without_repeating_subcommands():
    spec = completions._completion_spec()

    assert "list" in spec.command_words["config"]
    assert "--format" in spec.nested_words[("config", "list")]
    assert "show" not in spec.nested_words[("config", "list")]
