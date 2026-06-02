from __future__ import annotations

import pytest

from code_review_loop import harnesses


def test_claude_adapter_commands():
    adapter = harnesses.ClaudeHarnessAdapter()
    for role in ["review", "triage", "remediation", "commit-message"]:
        req = harnesses.PhaseCommandRequest(
            harness="claude",
            role=role,
            executable="claude",
            model="m1",
            sandbox="read-only",
        )
        cmd = adapter.command(req)
        assert cmd[0] == "claude"
        assert "--print" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "plan"
        assert "--model" in cmd
        assert "m1" in cmd


def test_gemini_adapter_commands():
    adapter = harnesses.GeminiHarnessAdapter()
    for role in ["review", "triage", "remediation", "commit-message"]:
        req = harnesses.PhaseCommandRequest(
            harness="gemini", role=role, executable="gemini", model="m1"
        )
        cmd = adapter.command(req)
        assert cmd[0] == "gemini"
        assert cmd[cmd.index("--approval-mode") + 1] == "auto_edit"
        assert "--model" in cmd
        assert "m1" in cmd
        assert "--prompt" not in cmd
        assert "" not in cmd


def test_gemini_review_command_uses_plan_approval_mode():
    command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="gemini",
            role="review",
            executable="gemini",
            model="gemini-3.1-pro-preview",
            sandbox="read-only",
            full_auto=False,
        )
    )

    assert command == [
        "gemini",
        "--approval-mode",
        "plan",
        "--model",
        "gemini-3.1-pro-preview",
    ]


def test_opencode_adapter_commands():
    adapter = harnesses.OpenCodeHarnessAdapter()
    for role in ["review", "triage", "remediation", "commit-message"]:
        req = harnesses.PhaseCommandRequest(
            harness="opencode", role=role, executable="oc", model="m2"
        )
        cmd = adapter.command(req)
        assert cmd[0] == "oc"
        assert "run" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "--model" in cmd
        assert "m2" in cmd


def test_opencode_adapter_debug_env_adds_provider_logs(monkeypatch):
    monkeypatch.setenv("REVREM_OPENCODE_DEBUG", "1")
    adapter = harnesses.OpenCodeHarnessAdapter()

    cmd = adapter.command(
        harnesses.PhaseCommandRequest(
            harness="opencode",
            role="review",
            executable="opencode",
            model="opencode/minimax-m3-free",
            sandbox="read-only",
            full_auto=False,
        )
    )

    assert cmd[:5] == ["opencode", "run", "--print-logs", "--log-level", "INFO"]
    assert "--model" in cmd


def test_kilo_adapter_commands():
    adapter = harnesses.KiloHarnessAdapter()
    for role in ["review", "triage", "remediation", "commit-message"]:
        req = harnesses.PhaseCommandRequest(
            harness="kilo", role=role, executable="kilo", model="m3"
        )
        cmd = adapter.command(req)
        assert cmd[0] == "kilo"
        assert "run" in cmd
        assert "--auto" in cmd
        assert "--model" in cmd
        assert "m3" in cmd


def test_prompt_invocation_uses_stdin_for_claude():
    command, stdin = harnesses.prepare_prompt_invocation(
        "claude",
        ["claude", "--print"],
        "review prompt",
    )
    assert command == ["claude", "--print"]
    assert stdin == "review prompt"


def test_prompt_invocation_passes_prompt_via_stdin_for_all_harnesses():
    command, stdin = harnesses.prepare_prompt_invocation(
        "opencode",
        ["opencode", "run"],
        "review prompt",
    )
    assert command == ["opencode", "run"]
    assert stdin == "review prompt"

    command, stdin = harnesses.prepare_prompt_invocation(
        "kilo",
        ["kilo", "run"],
        "review prompt",
    )
    assert command == ["kilo", "run"]
    assert stdin == "review prompt"

    command, stdin = harnesses.prepare_prompt_invocation(
        "gemini",
        ["gemini", "--approval-mode", "auto_edit"],
        "review prompt",
    )
    assert command == ["gemini", "--approval-mode", "auto_edit"]
    assert stdin == "review prompt"


@pytest.mark.parametrize(
    "harness,executable,expected_command,expects_stdin",
    [
        (
            "claude",
            "claude",
            ["claude", "--print", "--permission-mode", "auto", "--model", "M"],
            True,
        ),
        (
            "gemini",
            "gemini",
            [
                "gemini",
                "--approval-mode",
                "auto_edit",
                "--model",
                "M",
            ],
            True,
        ),
        (
            "opencode",
            "opencode",
            [
                "opencode",
                "run",
                "--dangerously-skip-permissions",
                "--model",
                "M",
            ],
            True,
        ),
        (
            "kilo",
            "kilo",
            ["kilo", "run", "--auto", "--model", "M"],
            True,
        ),
    ],
)
def test_full_noninteractive_invocation_matches_real_cli_contract(
    harness, executable, expected_command, expects_stdin
):
    # Encodes the verified non-interactive contract of each installed CLI for a
    # full_auto / workspace-write remediation: the exact argv plus whether the
    # prompt is delivered on stdin or as an argument.
    request = harnesses.PhaseCommandRequest(
        harness=harness,
        role="remediation",
        executable=executable,
        model="M",
        sandbox="workspace-write",
        full_auto=True,
    )
    base_command = harnesses.build_phase_command(request)
    command, stdin = harnesses.prepare_prompt_invocation(
        harness, base_command, "PROMPT"
    )
    if expects_stdin:
        assert stdin == "PROMPT"
        assert command == expected_command
    else:
        assert stdin is None
        assert command == expected_command
