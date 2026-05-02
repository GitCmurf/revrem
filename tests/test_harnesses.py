from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import harnesses


def test_codex_adapter_builds_review_command():
    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="codex",
            role="review",
            executable="codex",
            base="main",
            model="gpt-5.5",
            reasoning_effort="medium",
        )
    )

    assert command == [
        "codex",
        "-c",
        'model_reasoning_effort="medium"',
        "--model",
        "gpt-5.5",
        "review",
        "--base",
        "main",
    ]


def test_codex_adapter_builds_remediation_exec_command():
    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="codex",
            role="remediation",
            executable="codex",
            model="gpt-5.4-mini",
            reasoning_effort="low",
            sandbox="workspace-write",
            color="never",
            json_output=True,
            output_last_message_path=Path("last.txt"),
        )
    )

    assert command[:6] == [
        "codex",
        "exec",
        "-c",
        'model_reasoning_effort="low"',
        "--full-auto",
        "--sandbox",
    ]
    assert "--json" in command
    assert command[command.index("--model") + 1] == "gpt-5.4-mini"
    assert command[-3:] == ["--output-last-message", "last.txt", "-"]


def test_reserved_harnesses_are_valid_but_not_executable():
    with pytest.raises(NotImplementedError, match="claude"):
        harnesses.build_phase_command(
            harnesses.PhaseCommandRequest(
                harness="claude",
                role="review",
                executable="claude",
            )
        )
