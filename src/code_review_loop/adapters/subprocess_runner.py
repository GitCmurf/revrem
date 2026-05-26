"""ProcessRunner adapter backed by subprocesses."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import harnesses
from code_review_loop.adapters import terminal as terminal_adapter
from code_review_loop.adapters.phase_support import _timeout_stream_text
from code_review_loop.core.ports import CommandResult


def default_runner(
    args: Sequence[str],
    cwd: Path,
    input_text: str | None = None,
    timeout_seconds: float | None = None,
) -> CommandResult:
    if harnesses.is_fake_harness_command(tuple(args)):
        returncode, stdout, stderr = harnesses.run_fake_harness_command(tuple(args))
        return CommandResult(
            args=list(args),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            tokens=harnesses.fake_harness_token_charge(tuple(args)),
        )
    try:
        completed = run_subprocess_with_terminal_title_refresh(
            list(args),
            cwd=cwd,
            input=input_text,
            timeout=timeout_seconds,
        )
        return CommandResult(
            args=list(args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_stream_text(exc.output)
        stderr = _timeout_stream_text(exc.stderr)
        timeout_note = (
            f"Command timed out after {timeout_seconds} second{'s' if timeout_seconds != 1 else ''}\n"
            f"Command: {shlex.join(list(args))}\n"
            f"cwd: {cwd}\n"
        )
        stderr = timeout_note + "\n[partial stderr]\n" + stderr if stderr else timeout_note
        return CommandResult(
            args=list(args),
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
        )


def run_subprocess_with_terminal_title_refresh(
    args: list[str],
    *,
    cwd: Path,
    input: str | None,
    timeout: float | None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = None if timeout is None else time.monotonic() + timeout  # det-exempt: governs a real subprocess I/O timeout; faking breaks process killing
    pending_input = input
    try:
        while True:
            terminal_adapter.refresh_terminal_title()
            wait = terminal_adapter.TERMINAL_TITLE_REFRESH_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()  # det-exempt: governs a real subprocess I/O timeout; faking breaks process killing
                if remaining <= 0:
                    kill_process_tree(process)
                    stdout, stderr = process.communicate()
                    assert timeout is not None
                    raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
                wait = min(wait, remaining)
            try:
                stdout, stderr = process.communicate(input=pending_input, timeout=wait)
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                # `communicate()` cannot accept stdin again after it has started.
                # Keep waiting without resending input; the subprocess object
                # retains any buffered stdin internally.
                pending_input = None
                pass
    except BaseException:
        try:
            if process.poll() is None:
                kill_process_tree(process)
            process.communicate()
        except Exception:
            pass
        raise


def kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Kill a POSIX/Linux subprocess group started with ``start_new_session``."""
    pid = getattr(process, "pid", None)
    if pid is None:
        process.kill()
        return
    if not hasattr(os, "killpg"):
        process.kill()
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
