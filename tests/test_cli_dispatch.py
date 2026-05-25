"""Registry dispatch coverage (REVREM-TASK-003 Wave C1a/C1b).

These tests pin the contract that ``code_review_loop.cli.main`` selects the
right subcommand module by name. We monkeypatch the per-subcommand entry point
(not ``run_loop``) so we can observe routing without invoking the loop, then
assert ``main`` returns whatever the handler returned and that the registry
keys cover every documented subcommand.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from code_review_loop import cli
from code_review_loop.cli import commands as cli_commands

_EXPECTED_SUBCOMMANDS = {
    "bundle-bug-report",
    "config",
    "doctor",
    "history",
    "policy",
    "preflight",
    "replay",
    "resume",
    "suppress",
    "triage",
    "ui",
}


def test_registry_keys_match_documented_subcommands() -> None:
    registry = cli._build_subcommand_registry()
    assert set(registry) == _EXPECTED_SUBCOMMANDS


@pytest.mark.parametrize(
    ("name", "module_attr"),
    [
        ("bundle-bug-report", "bundle"),
        ("config", "config"),
        ("doctor", "doctor"),
        ("history", "history"),
        ("policy", "policy"),
        ("preflight", "doctor"),
        ("replay", "replay"),
        ("resume", "resume"),
        ("suppress", "suppress"),
        ("triage", "triage"),
    ],
)
def test_main_dispatches_to_command_module(
    name: str, module_attr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    module = getattr(cli_commands, module_attr)

    def fake_main(argv: Sequence[str]) -> int:
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(module, "main", fake_main)
    rc = cli.main([name, "--flag", "value"])
    assert rc == 0
    assert seen["argv"] == ["--flag", "value"]


def test_main_dispatches_to_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    from code_review_loop import tui

    captured: dict[str, object] = {}

    def fake_tui_main(argv: Sequence[str]) -> int:
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr(tui, "main", fake_tui_main)
    rc = cli.main(["ui", "--mode", "compact"])
    assert rc == 0
    assert captured["argv"] == ["--mode", "compact"]


def test_main_falls_through_when_no_subcommand_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An argv whose first token is not in the registry must reach parse_args.
    # We patch parse_args to short-circuit before build_loop_config so the
    # test exercises only the dispatcher, not the loop construction path.
    called: dict[str, object] = {}

    def fake_parse_args(argv: Sequence[str]):
        called["argv"] = list(argv)
        raise SystemExit(99)

    monkeypatch.setattr(cli, "parse_args", fake_parse_args)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["definitely-not-a-subcommand", "--whatever"])
    assert excinfo.value.code == 99
    assert called["argv"] == ["definitely-not-a-subcommand", "--whatever"]
