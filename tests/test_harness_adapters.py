from __future__ import annotations

from pathlib import Path

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


def test_opencode_debug_argv_is_well_formed(monkeypatch):
    """Structural lock: the REVREM_OPENCODE_DEBUG argv shape is frozen.

    This is a *structural*, not a *behavioral* check: we do not invoke
    ``opencode run --help`` here, so a future opencode release that
    renames ``--print-logs`` or ``--log-level`` would still need an edit
    at the ``OPENCODE_DEBUG_ARGV`` constant, but this test will not
    detect the rename on its own. The structural guards below catch
    silent flag-rename regressions (e.g., the constant being reordered
    or a token silently losing its leading ``--``).

    The ``unset`` branch (no debug flags injected) is covered by
    ``test_opencode_debug_argv_off_by_default`` below.
    """
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

    assert tuple(cmd[2 : 2 + len(harnesses.OPENCODE_DEBUG_ARGV)]) == (harnesses.OPENCODE_DEBUG_ARGV)
    argv = harnesses.OPENCODE_DEBUG_ARGV
    assert len(argv) >= 2, "OPENCODE_DEBUG_ARGV must contain at least one flag/value"
    for index, token in enumerate(argv[:-1]):
        assert token.startswith("--"), (
            f"OPENCODE_DEBUG_ARGV[{index}]={token!r} must be a long option"
        )
    assert not argv[-1].startswith("--"), (
        f"OPENCODE_DEBUG_ARGV terminal value {argv[-1]!r} must be a bare token"
    )
    assert harnesses.OPENCODE_DEBUG_ENV == "REVREM_OPENCODE_DEBUG"


def test_opencode_debug_argv_off_by_default(monkeypatch):
    """Without REVREM_OPENCODE_DEBUG=1, the debug flags must not be injected."""
    monkeypatch.delenv("REVREM_OPENCODE_DEBUG", raising=False)
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

    for flag in harnesses.OPENCODE_DEBUG_ARGV:
        assert flag not in cmd


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
        assert "--dangerously-skip-permissions" not in cmd


def test_kilo_adapter_omits_auto_for_unsupported_full_auto_sandbox_combos():
    adapter = harnesses.KiloHarnessAdapter()
    for full_auto, sandbox in (
        (True, "read-only"),
        (False, "workspace-write"),
        (False, "read-only"),
    ):
        req = harnesses.PhaseCommandRequest(
            harness="kilo",
            role="remediation",
            executable="kilo",
            model="m3",
            sandbox=sandbox,
            full_auto=full_auto,
        )
        cmd = adapter.command(req)
        assert cmd[0] == "kilo"
        assert "run" in cmd
        assert "--auto" not in cmd, (
            f"--auto must be absent for full_auto={full_auto} sandbox={sandbox}"
        )


def test_kilo_adapter_pins_verified_run_subcommand_contract():
    """Kilo is an opencode fork, but its top-level commands are not identical.

    RevRem only depends on the verified ``kilo run`` surface: ``--auto`` is
    accepted by ``kilo run --help`` for autonomous execution, while prompt
    delivery remains stdin instead of opencode's file-attachment path.
    """
    base_command = harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness="kilo",
            role="remediation",
            executable="kilo",
            model="provider/model",
            sandbox="workspace-write",
            full_auto=True,
        )
    )
    command, stdin = harnesses.prepare_prompt_invocation("kilo", base_command, "PROMPT")

    assert command == ["kilo", "run", "--auto", "--model", "provider/model"]
    assert stdin == "PROMPT"
    assert "--file" not in command


def test_prompt_invocation_uses_stdin_for_claude():
    command, stdin = harnesses.prepare_prompt_invocation(
        "claude",
        ["claude", "--print"],
        "review prompt",
    )
    assert command == ["claude", "--print"]
    assert stdin == "review prompt"


def test_prompt_invocation_uses_file_for_opencode(tmp_path):
    prompt_path = tmp_path / "prompt.txt"
    command, stdin = harnesses.prepare_prompt_invocation(
        "opencode",
        ["opencode", "run"],
        "review prompt",
        prompt_artifact_path=prompt_path,
    )
    assert command == [
        "opencode",
        "run",
        "Follow the attached RevRem prompt exactly.",
        "--file",
        str(prompt_path),
    ]
    assert stdin is None
    assert "review prompt" not in command


def test_prompt_invocation_passes_prompt_via_stdin_for_kilo():
    command, stdin = harnesses.prepare_prompt_invocation(
        "kilo",
        ["kilo", "run"],
        "review prompt",
    )
    assert command == ["kilo", "run"]
    assert stdin == "review prompt"


def test_prompt_invocation_passes_gemini_prompt_via_argv_prompt():
    command, stdin = harnesses.prepare_prompt_invocation(
        "gemini",
        ["gemini", "--approval-mode", "auto_edit"],
        "review prompt",
    )
    assert command == [
        "gemini",
        "--approval-mode",
        "auto_edit",
        "--prompt",
        "review prompt",
    ]
    assert stdin is None


def test_prompt_invocation_rejects_oversized_gemini_argv_prompt():
    prompt = "x" * (harnesses.GEMINI_ARGV_PROMPT_MAX_BYTES + 1)

    with pytest.raises(ValueError, match="gemini prompt exceeds"):
        harnesses.prepare_prompt_invocation(
            "gemini",
            ["gemini", "--approval-mode", "plan"],
            prompt,
        )


def test_prompt_invocation_rejects_oversized_multibyte_gemini_argv_prompt():
    prompt = "é" * (harnesses.GEMINI_ARGV_PROMPT_MAX_BYTES // 2 + 1)

    with pytest.raises(ValueError, match="gemini prompt exceeds"):
        harnesses.prepare_prompt_invocation(
            "gemini",
            ["gemini", "--approval-mode", "plan"],
            prompt,
        )


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
                "--prompt",
                "PROMPT",
            ],
            False,
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
                "Follow the attached RevRem prompt exactly.",
                "--file",
                "prompt.txt",
            ],
            False,
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
    prompt_path = None if harness != "opencode" else Path("prompt.txt")
    command, stdin = harnesses.prepare_prompt_invocation(
        harness,
        base_command,
        "PROMPT",
        prompt_artifact_path=prompt_path,
    )
    if expects_stdin:
        assert stdin == "PROMPT"
        assert command == expected_command
    else:
        assert stdin is None
        assert command == expected_command
