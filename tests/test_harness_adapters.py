from __future__ import annotations

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
        assert "--prompt" in cmd
        assert "" in cmd
        assert cmd[cmd.index("--approval-mode") + 1] == "auto_edit"
        assert "--model" in cmd
        assert "m1" in cmd
        assert cmd[cmd.index("--prompt") + 1] == ""


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


def test_prompt_invocation_uses_stdin_for_claude_and_gemini():
    command, stdin = harnesses.prepare_prompt_invocation(
        "claude",
        ["claude", "--print"],
        "review prompt",
    )
    assert command == ["claude", "--print"]
    assert stdin == "review prompt"

    command, stdin = harnesses.prepare_prompt_invocation(
        "gemini",
        ["gemini", "--prompt", ""],
        "review prompt",
    )
    assert command == ["gemini", "--prompt", ""]
    assert stdin == "review prompt"


def test_prompt_invocation_uses_message_argument_for_opencode_and_kilo():
    command, stdin = harnesses.prepare_prompt_invocation(
        "opencode",
        ["opencode", "run"],
        "review prompt",
    )
    assert command == ["opencode", "run", "review prompt"]
    assert stdin is None

    command, stdin = harnesses.prepare_prompt_invocation(
        "kilo",
        ["kilo", "run"],
        "review prompt",
    )
    assert command == ["kilo", "run", "review prompt"]
    assert stdin is None
