from __future__ import annotations

import io
import os
import shutil
import signal
import time
from importlib import import_module

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import application, waiting_progress
from code_review_loop.adapters import subprocess_runner as subprocess_runner_mod
from code_review_loop.adapters import terminal as terminal_mod
from code_review_loop.cli import config_builder
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.runner_finish import _latest_prompt_evidence

cli_main = import_module("code_review_loop.cli.main")


def test_loop_uses_phase_specific_timeouts_for_review_remediation_and_checks(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
        timeout_seconds=300,
        review_timeout_seconds=300,
        remediation_timeout_seconds=1800,
    )

    runner_mod.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, 1800, 300, 300]


def test_loop_keeps_checks_on_global_timeout_when_remediation_is_disabled(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
        timeout_seconds=300,
        review_timeout_seconds=300,
        remediation_timeout_seconds=0,
    )

    runner_mod.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, None, 300, 300]


def test_loop_preserves_disabled_global_timeout_for_remediation_and_checks(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
        timeout_seconds=None,
        review_timeout_seconds=300,
        remediation_timeout_seconds=None,
    )

    runner_mod.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, None, None, 300]


def test_loop_uses_default_timeout_when_phase_timeouts_are_unset(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="ok\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
    )

    runner_mod.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, 300, 300, 300]


def test_subprocess_refresh_loop_kills_child_on_interrupt(tmp_path, monkeypatch):
    refresh_calls = []

    class FakeProcess:
        def __init__(self):
            self.killed = False
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise KeyboardInterrupt
            assert self.killed is True
            assert input is None
            return ("stdout", "stderr")

        def kill(self):
            self.killed = True

        def poll(self):
            return None if not self.killed else 0

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        return fake_process

    def fake_refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr(subprocess_runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(terminal_mod, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(terminal_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    with pytest.raises(KeyboardInterrupt):
        subprocess_runner_mod.run_subprocess_with_terminal_title_refresh(
            ["codex", "exec"],
            cwd=tmp_path,
            input="prompt",
            timeout=1,
        )

    assert fake_process.killed is True
    assert fake_process.communicate_calls == 2
    assert len(refresh_calls) == 1


def test_repeated_cancellation_signal_within_window_is_marked_forced(monkeypatch):
    monkeypatch.setattr(terminal_mod, "_LAST_CANCELLATION_SIGNAL_AT", None)

    first = terminal_mod.cancellation_interrupt_for_signal(signal.SIGINT, now=100.0)
    second = terminal_mod.cancellation_interrupt_for_signal(signal.SIGINT, now=103.0)

    assert "controlled cancellation" in str(first)
    assert "forced cancellation" in str(second)


def test_cancellation_signal_after_window_starts_new_controlled_stop(monkeypatch):
    monkeypatch.setattr(terminal_mod, "_LAST_CANCELLATION_SIGNAL_AT", None)

    terminal_mod.cancellation_interrupt_for_signal(signal.SIGTERM, now=100.0)
    later = terminal_mod.cancellation_interrupt_for_signal(signal.SIGTERM, now=106.0)

    assert "controlled cancellation" in str(later)


def test_kill_process_tree_targets_child_process_group(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 12345

        def kill(self):
            calls.append(("kill", self.pid))

    def fake_killpg(pid, sig):
        calls.append(("killpg", pid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)

    subprocess_runner_mod.kill_process_tree(FakeProcess())

    assert calls == [("killpg", 12345, signal.SIGKILL)]


def test_latest_prompt_evidence_reports_cancelled_review_prompt(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "review-1-context.txt").write_text("context", encoding="utf-8")
    (artifact_dir / "review-1-prompt.txt").write_text("prompt text", encoding="utf-8")

    evidence = _latest_prompt_evidence(artifact_dir)

    assert evidence["latest_prompt_artifact"] == "review-1-prompt.txt"
    assert evidence["latest_prompt_phase"] == "review"
    assert evidence["latest_prompt_iteration"] == "1"
    assert evidence["latest_prompt_bytes"] == len("prompt text")
    assert evidence["latest_context_artifact"] == "review-1-context.txt"


def test_latest_prompt_evidence_handles_three_segment_commit_prompt(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "commit-1-message-prompt.txt").write_text("commit prompt", encoding="utf-8")

    evidence = _latest_prompt_evidence(artifact_dir)

    assert evidence["latest_prompt_artifact"] == "commit-1-message-prompt.txt"
    assert evidence["latest_prompt_phase"] == "commit"
    assert evidence["latest_prompt_iteration"] == "1"


def test_latest_prompt_evidence_drops_phase_for_unknown_artifact_name(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "diagnostic-1-prompt.txt").write_text("noise", encoding="utf-8")

    evidence = _latest_prompt_evidence(artifact_dir)

    assert evidence["latest_prompt_artifact"] == "diagnostic-1-prompt.txt"
    assert "latest_prompt_phase" not in evidence
    assert "latest_prompt_iteration" not in evidence


def test_subprocess_refresh_loop_does_not_resend_input_after_timeout(tmp_path, monkeypatch):
    refresh_calls = []

    class FakeProcess:
        def __init__(self):
            self.communicate_calls = 0
            self.returncode = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                assert input == "prompt"
                raise subprocess_runner_mod.subprocess.TimeoutExpired(["codex", "exec"], timeout)
            assert input is None
            return ("stdout", "stderr")

        def kill(self):
            raise AssertionError("kill should not be called for a normal timeout retry")

        def poll(self):
            return None

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        return fake_process

    def fake_refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr(subprocess_runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(terminal_mod, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(terminal_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    completed = subprocess_runner_mod.run_subprocess_with_terminal_title_refresh(
        ["codex", "exec"],
        cwd=tmp_path,
        input="prompt",
        timeout=1,
    )

    assert completed.stdout == "stdout"
    assert completed.stderr == "stderr"
    assert fake_process.communicate_calls == 2
    assert len(refresh_calls) == 2


def test_resolve_timeout_seconds_allows_disabling_timeout():
    assert config_builder.resolve_timeout_seconds(0) is None
    assert config_builder.resolve_timeout_seconds(900) == 900


def test_main_rejects_negative_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["--timeout-seconds", "-1"])

    assert exit_code == 1
    assert "--timeout-seconds must be 0 or greater" in capsys.readouterr().err


def test_main_rejects_nonpositive_max_iterations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["--max-iterations", "0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--max-iterations must be at least 1" in captured.err
    assert "Traceback" not in captured.err


def test_main_handles_keyboard_interrupt_without_traceback(tmp_path, monkeypatch, capsys):
    def interrupted_run_loop(config, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(application, "run_review_loop", interrupted_run_loop)

    exit_code = cli_main.main([])

    assert exit_code == 5
    assert capsys.readouterr().err == "Cancelled by user.\n"


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def test_default_runner_refreshes_active_terminal_title_during_child_process(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(terminal_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)
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
        result = subprocess_runner_mod.default_runner(
            [
                terminal_mod.sys.executable,
                "-c",
                "import time; time.sleep(0.05); print('done')",
            ],
            tmp_path,
            None,
            10,
        )

    output = stderr.getvalue()
    title_sequence = "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007"
    assert result.returncode == 0
    assert result.stdout == "done\n"
    assert output.count(title_sequence) >= 2
    assert output.endswith(terminal_mod.TERMINAL_TITLE_RESTORE)


def test_default_runner_does_not_refresh_terminal_title_during_rich_progress(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(terminal_mod.sys, "stderr", stderr)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(terminal_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)
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
        result = subprocess_runner_mod.default_runner(
            [
                terminal_mod.sys.executable,
                "-c",
                "import time; time.sleep(0.05); print('done')",
            ],
            tmp_path,
            None,
            10,
        )

    output = stderr.getvalue()
    title_sequence = "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007"
    assert result.returncode == 0
    assert result.stdout == "done\n"
    assert title_sequence not in output
    assert output.endswith(terminal_mod.TERMINAL_TITLE_RESTORE)


def test_subprocess_refresh_loop_stops_resending_stdin_after_timeout(tmp_path, monkeypatch):
    refresh_calls = []

    class FakeStdin:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.returncode = 0
            self.communicate_calls = 0
            self.inputs = []

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            self.inputs.append(input)
            if self.communicate_calls == 1:
                assert input == "prompt"
                raise subprocess_runner_mod.subprocess.TimeoutExpired(["codex", "exec"], timeout)
            assert input is None
            assert not self.stdin.closed, "stdin should stay open while waiting on the same child"
            return ("stdout", "stderr")

        def kill(self):
            raise AssertionError("deadline branch is not expected in this test")

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        return fake_process

    def fake_refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr(subprocess_runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(terminal_mod, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(terminal_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    result = subprocess_runner_mod.run_subprocess_with_terminal_title_refresh(
        ["codex", "exec"],
        cwd=tmp_path,
        input="prompt",
        timeout=1,
    )

    assert result.stdout == "stdout"
    assert result.stderr == "stderr"
    assert fake_process.stdin.closed is False
    assert fake_process.communicate_calls == 2
    assert fake_process.inputs == ["prompt", None]
    assert len(refresh_calls) == 2


def test_subprocess_runner_emits_waiting_progress_while_child_is_running(tmp_path, monkeypatch):
    reports: list[float] = []
    monotonic_values = iter([0.0, 1.0, 6.0])

    class FakeProcess:
        returncode = 0

        def __init__(self):
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess_runner_mod.subprocess.TimeoutExpired(["opencode", "run"], timeout)
            return ("stdout", "stderr")

        def poll(self):
            return None

        def kill(self):
            raise AssertionError("process should not be killed")

    fake_process = FakeProcess()

    monkeypatch.setattr(
        subprocess_runner_mod.subprocess,
        "Popen",
        lambda *args, **kwargs: fake_process,
    )
    monkeypatch.setattr(
        subprocess_runner_mod.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        waiting_progress,
        "WAITING_PROGRESS_INTERVAL_SECONDS",
        5.0,
    )

    with waiting_progress.subprocess_waiting_reporter(reports.append):
        result = subprocess_runner_mod.run_subprocess_with_terminal_title_refresh(
            ["opencode", "run"],
            cwd=tmp_path,
            input=None,
            timeout=None,
        )

    assert result.stdout == "stdout"
    assert reports == [6.0]


def test_default_runner_timeout_records_command_cwd_and_partial_output(tmp_path, monkeypatch):
    def fake_run_subprocess(*args, **kwargs):
        raise subprocess_runner_mod.subprocess.TimeoutExpired(
            ["codex", "exec"],
            12,
            output="partial stdout\n",
            stderr="partial stderr\n",
        )

    monkeypatch.setattr(
        subprocess_runner_mod, "run_subprocess_with_terminal_title_refresh", fake_run_subprocess
    )

    result = subprocess_runner_mod.default_runner(["codex", "exec"], tmp_path, "prompt", 12)

    assert result.returncode == -1
    assert result.stdout == "partial stdout\n"
    assert "Command timed out after 12 seconds" in result.stderr
    assert "Command: codex exec" in result.stderr
    assert f"cwd: {tmp_path}" in result.stderr
    assert "[partial stderr]\npartial stderr" in result.stderr


def test_default_runner_timeout_kills_process_group_with_pipe_holding_child(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("bash is required for the pipe-holding child process fixture")

    start = time.monotonic()

    result = subprocess_runner_mod.default_runner(
        ["bash", "-lc", "sleep 30 & wait"],
        tmp_path,
        None,
        0.2,
    )

    assert time.monotonic() - start < 5
    assert result.returncode == -1
    assert "Command timed out after 0.2 seconds" in result.stderr
