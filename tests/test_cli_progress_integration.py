from __future__ import annotations

import io
import re
from pathlib import Path

import tests.support.application_runner as runner_mod
from code_review_loop import progress
from code_review_loop.adapters import phase_support
from code_review_loop.adapters import terminal as terminal_mod
from code_review_loop.adapters.phase_support import progress_event
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RunContext
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs


def make_run_context(runner) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )


def test_progress_logs_review_and_finding_summaries(tmp_path, capsys):
    review_outputs = iter(
        [
            "The query surfaces disagree.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix queue parity — src/state.py:1\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    runner_mod.run_loop(config, runner)
    captured = capsys.readouterr()

    assert re.search(
        r"\d{2}:\d{2}:\d{2}\|rev\|1\s{3}\|start: codex review · sandbox read-only",
        captured.err,
    )
    assert re.search(
        r"\d{2}:\d{2}:\d{2}\|rev\|1\s{3}\|issue: The query surfaces disagree\.",
        captured.err,
    )
    assert "findings-summary" not in captured.err
    assert "|rev|1   |[P2]   Fix queue parity" in captured.err
    assert "|rem|1   |done" in captured.err


def test_compact_progress_uses_local_wall_time(monkeypatch):
    class FakeNow:
        def strftime(self, fmt):
            assert fmt == "%H:%M:%S"
            return "12:34:56"

    class FakeDateTime:
        @classmethod
        def now(cls):
            return FakeNow()

    monkeypatch.setattr(phase_support, "datetime", FakeDateTime)

    assert phase_support.compact_progress_prefix("review", "1") == "12:34:56|rev|1   |"


def test_rich_progress_falls_back_to_compact_once(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(progress, "print_rich_event", lambda *args, **kwargs: False)
    monkeypatch.setattr(phase_support, "_RICH_UNAVAILABLE_WARNED", False)
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
    )

    ctx = make_run_context(lambda *_args, **_kwargs: CommandResult([], 0))
    progress_event(config, "review", "1", "start", "codex review --base main", ctx=ctx)
    progress_event(config, "review", "1", "clear", ctx=ctx)
    captured = capsys.readouterr()

    assert captured.err.count("rich progress unavailable; using compact output") == 1
    assert "start: codex review --base main" in captured.err
    assert "|rev|1   |clear" in captured.err


def test_rich_progress_renderer_is_used_when_available(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(
        progress,
        "print_rich_event",
        lambda phase, label, status, detail="": calls.append(
            (phase, label, status, detail)
        )
        or True,
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
    )

    ctx = make_run_context(lambda *_args, **_kwargs: CommandResult([], 0))
    progress_event(config, "review", "1", "start", "codex review --base main", ctx=ctx)

    assert calls == [("review", "1", "start", "codex review --base main")]
    assert capsys.readouterr().err == ""


def test_compact_progress_wraps_to_terminal_width(tmp_path, capsys, monkeypatch):
    from code_review_loop.adapters import phase_support

    monkeypatch.setattr(phase_support, "terminal_columns", lambda default=120: 70)
    review_outputs = iter(
        [
            "This review summary is long enough to wrap onto another aligned line.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix queue parity — src/state.py:1\n"
            "  This detail is also long enough to wrap under the same text column.\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    runner_mod.run_loop(config, runner)
    captured = capsys.readouterr()

    assert re.search(
        r"\n\d\d:\d\d:\d\d\|rev\|1\s+\|\s+onto another aligned line\.", captured.err
    )
    assert re.search(
        r"\n\d\d:\d\d:\d\d\|rev\|1\s+\|\s+the same text column\.", captured.err
    )


def test_progress_logs_finding_detail_lines(tmp_path, capsys):
    review_outputs = iter(
        [
            "Full review comments:\n\n"
            "- [P2] Fix queue parity — src/state.py:1\n"
            "  This is the important detail.\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    runner_mod.run_loop(config, runner)
    captured = capsys.readouterr()

    assert "This is the important detail." in captured.err
    assert re.search(
        r"\n\d\d:\d\d:\d\d\|rev\|1\s+\|\s+This is the important detail\.", captured.err
    )


def test_compact_progress_repeats_prefix_on_every_wrapped_line(monkeypatch):
    monkeypatch.setattr(phase_support, "terminal_columns", lambda default=120: 58)

    lines = phase_support.wrap_progress_text(
        "12:34:56|tri|1   |",
        "codex exec [contract=v2 source=mixed harness=codex model=gpt-5.5 timeout=0]",
        head="start: ",
    )

    assert len(lines) > 1
    assert all(line.startswith("12:34:56|tri|1   |") for line in lines)
    assert "source=mixed" in " ".join(lines)


def test_resolved_phase_detail_summarizes_prompt_arguments():
    detail = phase_support.resolved_phase_detail(
        [
            "gemini",
            "--approval-mode",
            "plan",
            "--prompt",
            "first line\n\nsecond line with much more detail",
        ],
        harness="gemini",
        model="gemini-3.1-pro-preview",
        reasoning_effort=None,
        timeout_seconds=0,
        prompt_chars=1234,
        prompt_delivery="stdin",
    )

    assert detail.startswith("gemini · gemini-3.1-pro-preview")
    assert "\\n" not in detail
    assert "prompt=1.2k stdin" in detail
    assert "first line second line" not in detail


def test_resolved_phase_detail_summarizes_opencode_without_repetition():
    detail = phase_support.resolved_phase_detail(
        ["opencode", "run", "--model", "opencode/minimax-m3-free"],
        harness="opencode",
        model="opencode/minimax-m3-free",
        reasoning_effort="low",
        timeout_seconds=0,
        sandbox="read-only",
        source="mixed",
        prompt_chars=126_668,
        prompt_delivery="file",
    )

    assert detail == (
        "opencode run · opencode/minimax-m3-free · n/a effort · timeout=0 · "
        "sandbox read-only · prompt=126.7k file · source=profile+cli"
    )
    assert "--model" not in detail
    assert detail.count("opencode/minimax-m3-free") == 1


def test_resolved_phase_detail_shows_external_review_truncation_status():
    truncated = phase_support.resolved_phase_detail(
        ["gemini", "--model", "gemini-3.1-pro-preview"],
        harness="gemini",
        model="gemini-3.1-pro-preview",
        reasoning_effort="low",
        timeout_seconds=0,
        sandbox="read-only",
        source="mixed",
        prompt_chars=80_000,
        prompt_delivery="stdin",
        prompt_context_chars=466_882,
        prompt_truncated=True,
    )
    full = phase_support.resolved_phase_detail(
        ["gemini", "--model", "gemini-3.1-pro-preview"],
        harness="gemini",
        model="gemini-3.1-pro-preview",
        reasoning_effort="low",
        timeout_seconds=0,
        sandbox="read-only",
        source="mixed",
        prompt_chars=466_882,
        prompt_delivery="stdin",
        prompt_context_chars=466_882,
        prompt_truncated=False,
    )

    assert "prompt=80.0k/466.9k stdin truncated" in truncated
    assert "prompt=466.9k stdin full" in full


def test_progress_logs_unstructured_review_finding_summary(tmp_path, capsys):
    review_outputs = iter(
        [
            "The review model reported a regression in the route selection.\n"
            "REVIEW_STATUS: findings\n",
            "No findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    runner_mod.run_loop(config, runner)
    captured = capsys.readouterr()

    assert "review: The review model reported a regression" in captured.err
    assert re.search(r"\n\d\d:\d\d:\d\d\|rev\|1\s+\|findings", captured.err)


def test_quiet_progress_suppresses_progress_logs(tmp_path, capsys):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="No findings.\n")
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
    )

    runner_mod.run_loop(config, runner)
    captured = capsys.readouterr()

    assert captured.err == ""


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def test_terminal_title_tracks_review_and_remediation_phases(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)
    review_outputs = iter(
        [
            "Needs work.\nREVIEW_STATUS: findings\n",
            "No findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
    output = stderr.getvalue()

    assert summary["final_status"] == "clear"
    assert output.startswith(terminal_mod.TERMINAL_TITLE_SAVE)
    assert "\033]0;rev 1/2 RevRem\007\033]2;rev 1/2 RevRem\007" in output
    assert "\033]0;rem 1/2 RevRem\007\033]2;rem 1/2 RevRem\007" in output
    assert "\033]0;rev 2/2 RevRem\007\033]2;rev 2/2 RevRem\007" in output
    assert output.endswith(
        terminal_mod.TERMINAL_TITLE_RESTORE + terminal_mod.CURSOR_SHOW
    )


def test_terminal_title_restores_after_remediation_failure(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(
                list(args), 0, stdout="Needs work.\nREVIEW_STATUS: findings\n"
            )
        return CommandResult(list(args), 1, stderr="failed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    try:
        runner_mod.run_loop(config, runner)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected remediation failure")

    output = stderr.getvalue()
    assert "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007" in output
    assert "\033]0;rem 1/1 RevRem\007\033]2;rem 1/1 RevRem\007" in output
    assert output.endswith(
        terminal_mod.TERMINAL_TITLE_RESTORE + terminal_mod.CURSOR_SHOW
    )


def test_terminal_title_never_writes_to_stdout(tmp_path, monkeypatch):
    stderr = io.StringIO()
    stdout = TtyBuffer()
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)
    monkeypatch.setattr(terminal_mod.sys, "stdout", stdout)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    terminal_mod.set_terminal_title(config, "rev 1/1 RevRem")

    assert stderr.getvalue() == ""
    assert stdout.getvalue() == ""


def test_terminal_title_is_suppressed_in_rich_mode_to_avoid_escape_leaks(
    tmp_path, monkeypatch
):
    stderr = TtyBuffer()
    tty_sequences = []
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)
    monkeypatch.setattr(
        terminal_mod,
        "write_terminal_control_to_tty",
        lambda sequence: tty_sequences.append(sequence) or True,
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
        terminal_title=True,
    )

    with terminal_mod.terminal_title_context(config):
        terminal_mod.set_terminal_title(config, "rev 1/1 RevRem")
        terminal_mod.refresh_terminal_title()

    assert stderr.getvalue() == "".join(
        (
            terminal_mod.TERMINAL_TITLE_SAVE,
            terminal_mod.CURSOR_SHOW,
            terminal_mod.TERMINAL_TITLE_RESTORE,
        )
    )
    assert tty_sequences == []


def test_phase_terminal_title_skips_dev_tty_on_windows(tmp_path, monkeypatch):
    stderr = io.StringIO()
    monkeypatch.setattr(phase_support.sys, "stderr", stderr)
    monkeypatch.setattr(phase_support.os, "name", "nt")
    monkeypatch.setattr(
        phase_support.Path,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("/dev/tty opened")
        ),
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    phase_support.set_phase_terminal_title(config, "review", "1")

    assert stderr.getvalue() == ""


def test_terminal_title_context_restores_cursor_on_exit(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    with terminal_mod.terminal_title_context(config):
        terminal_mod.set_terminal_title(config, "rev 1/1 RevRem")

    output = stderr.getvalue()
    assert terminal_mod.CURSOR_SHOW in output
    assert output.endswith(terminal_mod.TERMINAL_TITLE_RESTORE)


def test_progress_warning_context_resets_rich_unavailable_latch(tmp_path, capsys):
    phase_support._RICH_UNAVAILABLE_WARNED = True

    with phase_support.progress_warning_context():
        phase_support.warn_rich_unavailable("review", "1")
        phase_support.warn_rich_unavailable("review", "1")

    captured = capsys.readouterr()
    assert captured.err.count("rich progress unavailable") == 1
    assert phase_support._RICH_UNAVAILABLE_WARNED is True
