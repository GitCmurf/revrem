"""ProcessRunner adapter backed by subprocesses."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import harnesses, waiting_progress
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
        stdout, tokens, provider_events = _normalize_codex_json(list(args), completed.stdout)
        return CommandResult(
            args=list(args),
            returncode=completed.returncode,
            stdout=stdout,
            stderr=completed.stderr,
            tokens=tokens,
            provider_events=provider_events,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_stream_text(exc.output)
        stdout, tokens, provider_events = _normalize_codex_json(list(args), stdout)
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
            tokens=tokens,
            provider_events=provider_events,
        )


def _normalize_codex_json(args: list[str], stdout: str) -> tuple[str, int | None, str | None]:
    """Keep raw JSONL while returning final assistant text to existing classifiers."""
    if "--json" not in args:
        return stdout, None, None
    final_text: str | None = None
    tokens: int | None = None
    parsed_any = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        parsed_any = True
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") in {"agent_message", "assistant_message"}:
            candidate = item.get("text") or item.get("content")
            if isinstance(candidate, str):
                final_text = candidate
        usage = event.get("usage")
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            if not isinstance(total, int):
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")
                total = (
                    input_tokens + output_tokens
                    if isinstance(input_tokens, int) and isinstance(output_tokens, int)
                    else None
                )
            if isinstance(total, int):
                tokens = total
    if not parsed_any:
        return stdout, None, None
    normalized = (final_text.rstrip() + "\n") if final_text else ""
    return normalized, tokens, stdout


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
    deadline = (
        None if timeout is None else time.monotonic() + timeout
    )  # det-exempt: governs a real subprocess I/O timeout; faking breaks process killing
    pending_input = input
    started_at = time.monotonic()  # det-exempt: progress heartbeat for real subprocesses
    next_waiting_progress_at = started_at + waiting_progress.WAITING_PROGRESS_INTERVAL_SECONDS
    try:
        while True:
            terminal_adapter.refresh_terminal_title()
            reporter = waiting_progress.current_reporter()
            now = time.monotonic()  # det-exempt: progress heartbeat for real subprocesses
            if reporter is not None and now >= next_waiting_progress_at:
                reporter(now - started_at)
                next_waiting_progress_at = now + waiting_progress.WAITING_PROGRESS_INTERVAL_SECONDS
            wait = terminal_adapter.TERMINAL_TITLE_REFRESH_SECONDS
            if deadline is not None:
                remaining = (
                    deadline - time.monotonic()
                )  # det-exempt: governs a real subprocess I/O timeout; faking breaks process killing
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
