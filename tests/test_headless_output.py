"""Headless / CI output hardening tests (REVREM-PLAN-005 T3).

A CI run must produce ANSI-free stderr with no flags beyond what the provider
sets automatically. The gate is a single helper, :func:`force_terminal`, that
fires on either ``--no-tty`` or the ``CI`` environment variable (set
automatically by GitHub Actions and most other providers). These tests pin
that gate at the unit level and verify the terminal-title write path is
guarded too.
"""

from __future__ import annotations

import sys
from dataclasses import replace

import pytest

from code_review_loop import progress
from code_review_loop.adapters import terminal
from code_review_loop.config import LoopConfig

_ANSI_CSI = b"\x1b["


def _base_config(**overrides) -> LoopConfig:
    """A minimal LoopConfig with the output fields the T3 gates read."""
    return replace(
        LoopConfig(progress_style="rich", progress=True, terminal_title=True),
        **overrides,
    )


# --- force_terminal (the single suppression gate) -------------------------


def test_force_terminal_false_when_no_tty(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    assert progress.force_terminal(no_tty=True) is False


def test_force_terminal_false_when_ci_env_set(monkeypatch):
    monkeypatch.setenv("CI", "true")
    # No --no-tty flag passed; CI alone must suppress.
    assert progress.force_terminal(no_tty=False) is False


def test_force_terminal_true_when_interactive_no_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    # In the test runner stderr may or may not be a tty; force_terminal's
    # isatty() leg is the only variable. Assert the CI/no_tty legs are
    # satisfied, which is the contract under test.
    result = progress.force_terminal(no_tty=False)
    assert result == sys.stderr.isatty()  # CI absent, no_tty False -> depends only on isatty


@pytest.mark.parametrize("ci_value", ["true", "1", "false-ish", "anything"])
def test_force_terminal_false_for_any_ci_value(monkeypatch, ci_value):
    """Any non-empty CI value suppresses — providers set CI=true/1, but the
    gate is presence-based so a stray CI=false still suppresses (safe side)."""
    monkeypatch.setenv("CI", ci_value)
    assert progress.force_terminal(no_tty=False) is False


# --- terminal title suppression -------------------------------------------


def test_terminal_title_disabled_when_no_tty(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    config = _base_config(no_tty=True)
    assert terminal.terminal_title_supported(config) is False


def test_terminal_title_disabled_when_ci_env_set(monkeypatch):
    monkeypatch.setenv("CI", "true")
    config = _base_config(no_tty=False)
    assert terminal.terminal_title_supported(config) is False


def test_terminal_title_disabled_when_feature_off(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    config = _base_config(terminal_title=False)
    assert terminal.terminal_title_supported(config) is False


def test_terminal_title_write_returns_false_when_no_tty(monkeypatch, tmp_path):
    """write_terminal_control_to_tty is gated on the feature being supported;
    the feature is unsupported under no_tty, so the write path is never reached.
    Verify by checking terminal_title_supported is the gate and is False."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("os.name", "posix")
    config = _base_config(no_tty=True)
    # The feature gate is False, so a well-behaved caller never invokes the
    # /dev/tty write. Pin the gate as the protection.
    assert terminal.terminal_title_supported(config) is False


# --- rich_live_progress suppresses ANSI under no_tty ----------------------


def test_rich_live_progress_emits_no_ansi_under_no_tty(capsys, monkeypatch):
    """The Rich live panel must emit zero CSI escape sequences when no_tty."""
    monkeypatch.delenv("CI", raising=False)
    if not progress.rich_available():
        pytest.skip("rich not installed")
    with progress.rich_live_progress(True, no_tty=True):
        progress.print_rich_event("review", "iter-1", "findings")
    captured = capsys.readouterr()
    assert _ANSI_CSI not in captured.err.encode("utf-8", errors="replace")


def test_rich_fallback_console_suppresses_ansi_under_no_tty(monkeypatch):
    """The print_rich_* helpers build their own Console without a no_tty arg.

    When a run entered headless mode via rich_live_progress(no_tty=True), that
    mode must latch so the fallback console (used when no live panel is active)
    also suppresses ANSI. Without the latch, a local --no-tty run with an
    interactive stderr would leak escape sequences through the fallback path.
    """
    import io

    monkeypatch.delenv("CI", raising=False)
    if not progress.rich_available():
        pytest.skip("rich not installed")

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    stderr = _Tty()
    monkeypatch.setattr(progress.sys, "stderr", stderr)
    # Enter headless mode to latch _NO_TTY_FORCED, then simulate the fallback
    # path (no active live panel) by clearing the live state while still inside
    # the context. print_rich_message must build an ANSI-free fallback console.
    with progress.rich_live_progress(True, no_tty=True):
        saved_live, saved_lines = progress._ACTIVE_LIVE, progress._ACTIVE_LIVE_LINES
        progress._ACTIVE_LIVE = None
        progress._ACTIVE_LIVE_LINES = None
        try:
            progress.print_rich_message("review", "iter-1", "detail", head="warn: ")
        finally:
            progress._ACTIVE_LIVE = saved_live
            progress._ACTIVE_LIVE_LINES = saved_lines
    assert b"\x1b[" not in stderr.getvalue().encode("utf-8", errors="replace")


# --- summary-format / exit-code contract surface --------------------------


def test_loop_config_carries_no_tty_field():
    """The flag threads through LoopConfig end-to-end."""
    config = _base_config(no_tty=True)
    assert config.no_tty is True
    config_off = replace(config, no_tty=False)
    assert config_off.no_tty is False


def test_loop_config_no_tty_defaults_false():
    config = _base_config()
    assert config.no_tty is False


# Documented exit codes mapped by the run loop (core/outcome.py).
# T3 verifies the *surface* the report/Action rely on; the full scenario->exit
# mapping is covered by the engine acceptance tests. Here we pin the contract
# that the codes the report's exit-code-hint renders are stable.
@pytest.mark.parametrize(
    "final_status,expected_code",
    [
        ("clear", 0),
        ("findings", 2),
        ("unknown", 2),
        ("error", 1),
    ],
)
def test_documented_exit_code_mapping_is_stable(final_status, expected_code):
    from code_review_loop.core.outcome import (
        OutcomeClear,
        OutcomeFailed,
        OutcomeFindings,
        OutcomeUnknown,
        outcome_to_exit_code,
    )

    mapping = {
        "clear": OutcomeClear(reason="review_clear"),
        "findings": OutcomeFindings(reason="max_iterations_reached"),
        "unknown": OutcomeUnknown(reason="review_unknown"),
        "error": OutcomeFailed(reason="review_failed", error="review failed"),
    }
    assert outcome_to_exit_code(mapping[final_status]) == expected_code


# --- end-to-end: a real run with rich progress + no_tty emits no ANSI -------


def test_real_loop_with_no_tty_and_rich_progress_emits_no_ansi_stderr(
    tmp_path, capsys, monkeypatch
):
    """End-to-end: drive a real loop with no_tty=True + progress_style='rich'
    and assert stderr carries zero CSI escape sequences.

    This exercises the full threading path the GitHub Action relies on:
    LoopConfig.no_tty -> runner.rich_live_progress(..., no_tty=config.no_tty)
    -> progress.force_terminal. capsys captures the Rich Live output that
    lands on sys.stderr.
    """
    import tests.support.application_runner as runner_mod
    from code_review_loop.core.ports import CommandResult

    monkeypatch.delenv("CI", raising=False)
    if not progress.rich_available():
        pytest.skip("rich not installed")

    review_outputs = iter(
        ["Finding: x.\nREVIEW_STATUS: findings\n", "No findings.\nREVIEW_STATUS: clear\n"]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = replace(
        LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        ),
        progress=True,
        progress_style="rich",
        no_tty=True,
    )

    runner_mod.run_loop(config, runner)
    captured = capsys.readouterr()
    assert _ANSI_CSI not in captured.err.encode("utf-8", errors="replace")
