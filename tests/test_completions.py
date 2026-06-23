from __future__ import annotations

import pytest

from code_review_loop.cli.commands import completions


@pytest.mark.parametrize("shell", ("bash", "zsh", "fish"))
def test_completions_emit_known_subcommand_and_flags(shell: str, capsys):
    assert completions.main([shell]) == 0
    out = capsys.readouterr().out
    assert "report" in out
    assert "completions" in out
    assert "--profile" in out or "-l profile" in out
    assert "--no-tty" in out or "-l no-tty" in out
