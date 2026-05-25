#!/usr/bin/env python3
"""Run a bounded Codex review/remediation loop against a base branch."""

from __future__ import annotations

import atexit
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple, assert_never, cast

from code_review_loop import (
    __version__,
    artifacts,
    budgets,
    bug_bundle as bug_bundle,
    diagnostics,
    events,
    harnesses,
    policy,
    profiles,
    progress,
    prompts_composer,
    run_history,
    triage,
)
from code_review_loop.clock import SYSTEM_CLOCK, Clock, utc_iso
from code_review_loop.config import LoopConfig
from code_review_loop.core.engine import (
    Action,
    CommitDone,
    ConfigSnapshot,
    Continue,
    LoopAccumulator,
    NoFinalReview,
    RemediationDone,
    RetryViaCommitHook,
    ReviewDone,
    TriageDone,
    PhaseEvent,
    decide as decide_engine,
)
from code_review_loop.core.outcome import (
    OutcomeClear,
    OutcomeFailed,
    OutcomeFindings,
    OutcomeUnknown,
    RunOutcome,
)
from code_review_loop.core.ports import (
    ChecksRequest,
    CommandResult,
    CommitRequest,
    EventSink,
    ProcessRunner,
    ProgressReporter,
    RemediationRequest,
    ReviewRequest,
    RunContext,
    TriageRequest,
)
from code_review_loop.core.review_interpretation import (
    actionable_review_output,
    detect_review_status,
    extract_finding_blocks,
    extract_review_summary,
    review_status_diagnostics as review_status_diagnostics,
    strip_finding_priority,
)
from code_review_loop.core.review_interpretation import (
    extract_finding_summaries as extract_finding_summaries,
)
from code_review_loop.core.state import RunState
from code_review_loop.identity import SYSTEM_IDENTITY, RunIdentity
from code_review_loop.runtime import RunLoopFailed as RunLoopFailed
from code_review_loop.runtime import format_terminal_summary as format_terminal_summary
from code_review_loop.adapters.phase_support import CommitFailed as CommitFailed
from code_review_loop.adapters.phase_support import lexical_git_repo_root as lexical_git_repo_root

# REVREM-TASK-003 Wave C2a: parsers and their shared choice tuples are
# canonical in ``cli/args.py``. Runner imports them from that canonical module
# so command parsing has a single implementation.
from code_review_loop.cli.args import (
    COMMIT_ON_HOOK_FAILURE_CHOICES as COMMIT_ON_HOOK_FAILURE_CHOICES,
)
from code_review_loop.cli.args import (
    PROGRESS_STYLE_CHOICES as PROGRESS_STYLE_CHOICES,
)
from code_review_loop.cli.args import (
    REASONING_EFFORT_CHOICES as REASONING_EFFORT_CHOICES,
)
from code_review_loop.cli.args import (
    parse_args as parse_args,
)
from code_review_loop.cli.args import (
    parse_bundle_bug_report_args as parse_bundle_bug_report_args,
)
from code_review_loop.cli.args import (
    parse_config_args as parse_config_args,
)
from code_review_loop.cli.args import (
    parse_doctor_args as parse_doctor_args,
)
from code_review_loop.cli.args import (
    parse_history_args as parse_history_args,
)
from code_review_loop.cli.args import (
    parse_policy_args as parse_policy_args,
)
from code_review_loop.cli.args import (
    parse_replay_args as parse_replay_args,
)
from code_review_loop.cli.args import (
    parse_resume_args as parse_resume_args,
)
from code_review_loop.cli.args import (
    parse_suppress_args as parse_suppress_args,
)
from code_review_loop.cli.args import (
    parse_triage_args as parse_triage_args,
)

# REVREM-TASK-003 Wave C2a: ``LoopConfig`` assembly + argument-resolution
# helpers now live in ``cli/config_builder.py``. Runner imports the canonical
# helpers directly so the executable loop and CLI config surface share one
# implementation.
from code_review_loop.cli.config_builder import (
    build_loop_config as build_loop_config,
)
from code_review_loop.cli.config_builder import (
    default_artifact_dir as default_artifact_dir,
)
from code_review_loop.cli.config_builder import (
    ensure_default_artifact_ignore as ensure_default_artifact_ignore,
)
from code_review_loop.cli.config_builder import (
    new_profile_from_args as new_profile_from_args,
)
from code_review_loop.cli.config_builder import (
    parse_harness_bin_overrides as parse_harness_bin_overrides,
)
from code_review_loop.cli.config_builder import (
    pick as pick,
)
from code_review_loop.cli.config_builder import (
    profile_from_loop_config as profile_from_loop_config,
)
from code_review_loop.cli.config_builder import (
    profile_or_default as profile_or_default,
)
from code_review_loop.cli.config_builder import (
    resolve_max_iterations as resolve_max_iterations,
)
from code_review_loop.cli.config_builder import (
    resolve_profile_timeout_seconds as resolve_profile_timeout_seconds,
)
from code_review_loop.cli.config_builder import (
    resolve_timeout_seconds as resolve_timeout_seconds,
)
from code_review_loop.cli.config_builder import (
    should_prompt_for_new_profile as should_prompt_for_new_profile,
)

PROGRESS_PHASE_CODES = {
    "check": "chk",
    "commit": "com",
    "remediate": "rem",
    "review": "rev",
    "triage": "tri",
}
COMPACT_PROGRESS_DETAIL_INDENT = 7
DEFAULT_TERMINAL_COLUMNS = 120
CANCELLATION_FORCE_WINDOW_SECONDS = 5.0
COMMIT_HOOK_FAILURE_RE = re.compile(
    r"\b("
    r"pre-commit|pre-push|commit hook|hook failed|"
    r"mypy|ruff|black|flake8|eslint|prettier|detect-secrets|"
    r"files? were modified by this hook|found \d+ errors?"
    r")\b",
    re.IGNORECASE,
)
_LAST_CANCELLATION_SIGNAL_AT: float | None = None

DEFAULT_REMEDIATION_PROMPT = """You are running a bounded review-remediation loop.

Review findings from the previous Codex review are included below. Remediate the valid actionable
findings to high quality while respecting this repository's AGENTS.md instructions.

Rules:
- Keep the patch focused on the review findings.
- Preserve existing user changes; do not revert unrelated work.
- Maintain the repository's Code + Documentation + Tests atomic-unit rule.
- Add or update tests for behavior changes.
- Run the most relevant verification commands before finishing.
- If a finding is invalid or impossible to fix safely, explain that in your final response.

Previous review output:
"""

DEFAULT_TRIAGE_PROMPT = """You are the triage step in a bounded review-remediation loop.

Read the review output and produce a concise implementation handoff for the
remediation agent. Do not edit files. Separate confirmed actionable findings,
likely false positives, implementation order, and verification commands.

Review and check output:
"""

DEFAULT_REVIEW_PROMPT = """Review the current repository changes against the configured base branch.

Prioritize correctness, security, behavioral regressions, missing tests, and
maintainability risks. Return findings first, with file and line references
where possible. End with `REVIEW_STATUS: findings` if remediation is required,
or `REVIEW_STATUS: clear` if no actionable findings remain.
"""

DEFAULT_COMMIT_MESSAGE_PROMPT = """Write one concise Conventional Commit subject for the staged RevRem remediation changes.

Rules:
- Output only the commit subject.
- Use Conventional Commit syntax, for example: fix(cli): stop after no-op remediation.
- Use imperative mood.
- End the subject with:  (RevRem)
- Keep it concise.
- Do not use Markdown or quotes.

Staged change summary:
"""

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


# xterm-compatible title-stack controls use CSI, not OSC.
TERMINAL_TITLE_SAVE = "\033[22;0t"
TERMINAL_TITLE_RESTORE = "\033[23;0t"
TERMINAL_TITLE_REFRESH_SECONDS = 1.0
_CURRENT_TERMINAL_TITLE_SEQUENCE: str | None = None
_TERMINAL_TITLE_PREFER_TTY: bool | None = False
_RICH_UNAVAILABLE_WARNED = False
CURSOR_SHOW = "\033[?25h"


def terminal_title_supported(config: LoopConfig) -> bool:
    return config.terminal_title and (sys.stderr.isatty() or Path("/dev/tty").exists())


def sanitize_terminal_title(value: str) -> str:
    return value.replace("\033", "").replace("\007", "").replace("\n", " ").replace("\r", " ")


def write_terminal_control(sequence: str, *, prefer_tty: bool = False) -> None:
    if prefer_tty and write_terminal_control_to_tty(sequence):
        return
    if sys.stderr.isatty():
        sys.stderr.write(sequence)
        sys.stderr.flush()
    elif not prefer_tty:
        write_terminal_control_to_tty(sequence)


def write_terminal_control_to_tty(sequence: str) -> bool:
    try:
        with Path("/dev/tty").open("w", encoding="utf-8") as tty:
            tty.write(sequence)
            tty.flush()
            return True
    except OSError:
        return False


def restore_terminal_display() -> None:
    """Best-effort terminal recovery for interrupted Rich/title sessions."""
    write_terminal_control(CURSOR_SHOW, prefer_tty=bool(_TERMINAL_TITLE_PREFER_TTY))


def set_terminal_title(config: LoopConfig, title: str) -> None:
    global _CURRENT_TERMINAL_TITLE_SEQUENCE
    if not terminal_title_supported(config):
        return
    if config.progress_style == "rich":
        return
    safe_title = sanitize_terminal_title(title)
    # OSC 0 sets icon + window title. OSC 2 explicitly sets the window/tab
    # title. Emitting both is harmless and covers more terminal emulators.
    _CURRENT_TERMINAL_TITLE_SEQUENCE = f"\033]0;{safe_title}\007\033]2;{safe_title}\007"
    write_terminal_control(_CURRENT_TERMINAL_TITLE_SEQUENCE)


def refresh_terminal_title(*, prefer_tty: bool | None = None) -> None:
    if _CURRENT_TERMINAL_TITLE_SEQUENCE:
        if prefer_tty is None:
            prefer_tty = _TERMINAL_TITLE_PREFER_TTY
        if prefer_tty is None:
            return
        write_terminal_control(_CURRENT_TERMINAL_TITLE_SEQUENCE, prefer_tty=prefer_tty)


def terminal_iteration_label(label: str, max_iterations: int) -> str:
    if label.isdecimal():
        return f"{label}/{max_iterations}"
    if label == "final":
        return "final"
    return label


def set_phase_terminal_title(config: LoopConfig, phase: str, label: str) -> None:
    if phase == "review":
        prefix = "rev"
    elif phase == "remediate":
        prefix = "rem"
    else:
        return
    set_terminal_title(
        config,
        f"{prefix} {terminal_iteration_label(label, config.max_iterations)} RevRem",
    )


@contextmanager
def terminal_title_context(config: LoopConfig):
    global _CURRENT_TERMINAL_TITLE_SEQUENCE, _TERMINAL_TITLE_PREFER_TTY
    if not terminal_title_supported(config):
        yield
        return
    previous_prefer_tty = _TERMINAL_TITLE_PREFER_TTY
    _TERMINAL_TITLE_PREFER_TTY = None if config.progress_style == "rich" else False
    # There is no reliable cross-terminal way to read the current title. Xterm-
    # compatible terminals support a title stack, which gives the desired
    # save/restore behavior without querying terminal state.
    write_terminal_control(TERMINAL_TITLE_SAVE, prefer_tty=bool(_TERMINAL_TITLE_PREFER_TTY))
    try:
        yield
    finally:
        _CURRENT_TERMINAL_TITLE_SEQUENCE = None
        restore_terminal_display()
        write_terminal_control(TERMINAL_TITLE_RESTORE, prefer_tty=bool(_TERMINAL_TITLE_PREFER_TTY))
        _TERMINAL_TITLE_PREFER_TTY = previous_prefer_tty


@contextmanager
def terminal_recovery_context():
    global _LAST_CANCELLATION_SIGNAL_AT
    previous_handlers: dict[signal.Signals, Any] = {}
    previous_cancellation_signal_at = _LAST_CANCELLATION_SIGNAL_AT
    _LAST_CANCELLATION_SIGNAL_AT = None
    handled_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGTSTP"):
        handled_signals.append(signal.SIGTSTP)

    def handle_signal(signum: int, frame: object | None) -> None:
        restore_terminal_display()
        if signum in {signal.SIGINT, signal.SIGTERM}:
            raise cancellation_interrupt_for_signal(signum, now=time.monotonic())  # det-exempt: real-time debounce of double Ctrl-C; faking breaks the cancellation semantic
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
        if hasattr(signal, "SIGTSTP") and signum == signal.SIGTSTP:
            signal.signal(signum, handle_signal)

    for sig in handled_signals:
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, handle_signal)
    atexit.register(restore_terminal_display)
    try:
        yield
    finally:
        restore_terminal_display()
        with suppress(ValueError):
            atexit.unregister(restore_terminal_display)
        _LAST_CANCELLATION_SIGNAL_AT = previous_cancellation_signal_at
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def cancellation_interrupt_for_signal(signum: int, *, now: float) -> KeyboardInterrupt:
    global _LAST_CANCELLATION_SIGNAL_AT
    forced = (
        _LAST_CANCELLATION_SIGNAL_AT is not None
        and now - _LAST_CANCELLATION_SIGNAL_AT <= CANCELLATION_FORCE_WINDOW_SECONDS
    )
    _LAST_CANCELLATION_SIGNAL_AT = now
    signal_name = signal.Signals(signum).name
    if forced:
        return KeyboardInterrupt(f"forced cancellation after repeated {signal_name}")
    return KeyboardInterrupt(f"controlled cancellation after {signal_name}")


def progress_log(config: LoopConfig, message: str) -> None:
    if not config.progress:
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")  # det-exempt: human-display timestamp (terminal output), not machine contract
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


def compact_progress_label(label: str) -> str:
    if label in {"initial", "review-initial"}:
        return "init"
    if label in {"final", "review-final"}:
        return "fin"
    if label.startswith("review-"):
        return label.removeprefix("review-")
    return label


def compact_progress_prefix(phase: str, label: str) -> str:
    timestamp = datetime.now().strftime("%H:%M:%S")  # det-exempt: human-display timestamp (terminal output), not machine contract
    phase_code = PROGRESS_PHASE_CODES.get(phase, phase[:3])
    return f"{timestamp}|{phase_code:<3}|{compact_progress_label(label):<4}|"


def terminal_columns(default: int = DEFAULT_TERMINAL_COLUMNS) -> int:
    try:
        if sys.stderr.isatty():
            return os.get_terminal_size(sys.stderr.fileno()).columns
    except OSError:
        pass
    return default


def wrap_progress_text(
    prefix: str,
    text: str,
    *,
    head: str = "",
    continuation_indent: int | None = None,
) -> list[str]:
    indent = len(head) if continuation_indent is None else continuation_indent
    first_width = max(20, terminal_columns() - len(prefix) - len(head))
    next_width = max(20, terminal_columns() - len(prefix) - indent)
    wrapped = textwrap.wrap(
        text,
        width=first_width,
        subsequent_indent="",
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    lines = [f"{prefix}{head}{wrapped[0]}"]
    for line in wrapped[1:]:
        for continuation in textwrap.wrap(
            line,
            width=next_width,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [line]:
            lines.append(f"{' ' * len(prefix)}{' ' * indent}{continuation}")
    return lines


def print_compact_progress(phase: str, label: str, text: str, *, head: str = "") -> None:
    prefix = compact_progress_prefix(phase, label)
    for line in wrap_progress_text(prefix, text, head=head):
        print(line, file=sys.stderr, flush=True)


def progress_event(config: LoopConfig, phase: str, label: str, status: str, detail: str = "", *, ctx: RunContext) -> None:
    sink = ctx.event_sink
    if sink is not None:
        payload: dict[str, Any] = {"summary": status}
        if detail:
            payload["message"] = detail
        sink.emit(
            _progress_event_kind(status),
            phase=phase,
            iteration=label,
            payload=payload,
        )
    # delegate rendering to the injected ProgressReporter if available
    if ctx.progress_reporter is not None:
        ctx.progress_reporter.phase(phase, label, status, detail)
        return
    if not config.progress:
        return
    if config.progress_style == "rich":
        if progress.print_rich_event(phase, label, status, detail):
            return
        warn_rich_unavailable(phase, label)
        if detail:
            print_compact_progress(phase, label, detail, head=f"{status}: ")
        else:
            print_compact_progress(phase, label, status)
        return
    if config.progress_style == "verbose":
        suffix = f": {detail}" if detail else ""
        progress_log(config, f"{phase} {label}: {status}{suffix}")
        return
    if detail:
        print_compact_progress(phase, label, detail, head=f"{status}: ")
    else:
        print_compact_progress(phase, label, status)


def _progress_event_kind(status: str) -> str:
    if status == "start":
        return "phase_start"
    if status in {"failed", "invalid"}:
        return "failure"
    if status in {"retry", "warning"}:
        return "warning"
    if status == "suppressed":
        return "suppressed"
    if status == "status-debug":
        return "status_classification"
    if status == "loaded":
        return "phase_output"
    return "phase_result"


def emit_loop_failure_event(
    config: LoopConfig,
    *,
    phase: str,
    iteration: int | str | None,
    reason: str,
    error: str,
    ctx: RunContext,
) -> None:
    if ctx.event_sink is None:
        return
    ctx.event_sink.emit(
        "failure",
        phase=phase,
        iteration=iteration,
        payload={
            "reason": reason,
            "message": error,
        },
    )


def warn_rich_unavailable(phase: str, label: str) -> None:
    global _RICH_UNAVAILABLE_WARNED
    if _RICH_UNAVAILABLE_WARNED:
        return
    _RICH_UNAVAILABLE_WARNED = True
    print_compact_progress(phase, label, "rich progress unavailable; using compact output", head="warn: ")


@contextmanager
def progress_warning_context():
    global _RICH_UNAVAILABLE_WARNED
    previous = _RICH_UNAVAILABLE_WARNED
    _RICH_UNAVAILABLE_WARNED = False
    try:
        yield
    finally:
        _RICH_UNAVAILABLE_WARNED = previous


def progress_continuation(config: LoopConfig, phase: str, label: str, text: str, indent: int = 2) -> None:
    if not config.progress:
        return
    if config.progress_style == "rich":
        if progress.print_rich_continuation(phase, label, text, indent=indent):
            return
        warn_rich_unavailable(phase, label)
    if config.progress_style == "verbose":
        progress_log(config, f"{phase} {label}: {' ' * indent}{text}")
        return
    prefix = compact_progress_prefix(phase, label)
    width = max(20, terminal_columns() - len(prefix) - indent)
    for line in textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]:
        print(f"{' ' * len(prefix)}{' ' * indent}{line}", file=sys.stderr, flush=True)


def default_runner(args: Sequence[str], cwd: Path, input_text: str | None = None, timeout_seconds: float | None = None) -> CommandResult:
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


def _timeout_stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


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
            refresh_terminal_title()
            wait = TERMINAL_TITLE_REFRESH_SECONDS
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
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()




def log_review_findings(config: LoopConfig, label: str, output: str, ctx: RunContext) -> bool:
    blocks = extract_finding_blocks(output)
    if not blocks:
        return False
    summary = extract_review_summary(output)
    if summary:
        if compact_progress_label(label) == "init":
            progress_continuation(config, "review", label, summary, indent=COMPACT_PROGRESS_DETAIL_INDENT)
        else:
            print_progress_message(config, "review", label, summary, head="issue: ")
    else:
        progress_event(config, "review", label, f"findings-summary ({len(blocks)})", ctx=ctx)
    for block in blocks:
        print_progress_message(
            config,
            "review",
            label,
            strip_finding_priority(block[0])[1],
            head=f"{strip_finding_priority(block[0])[0]:<7}",
        )
        for detail in block[1:]:
            progress_continuation(config, "review", label, detail, indent=COMPACT_PROGRESS_DETAIL_INDENT)
    return True


def print_progress_message(config: LoopConfig, phase: str, label: str, text: str, *, head: str = "") -> None:
    if not config.progress:
        return
    if config.progress_style == "rich":
        if progress.print_rich_message(phase, label, text, head=head):
            return
        warn_rich_unavailable(phase, label)
    if config.progress_style == "verbose":
        progress_log(config, f"{phase} {label}: {head}{text}")
        return
    print_compact_progress(phase, label, text, head=head)


def _resolve_executable(harness: str, config: LoopConfig) -> str:
    return harnesses.resolve_executable(harness, config.harness_executables, config.codex_bin)


def build_commit_message_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.commit_message_harness,
            role="commit-message",
            executable=_resolve_executable(config.commit_message_harness, config),
            model=config.commit_message_model,
            reasoning_effort=config.commit_reasoning_effort,
            sandbox="read-only",
            color=config.exec_color,
            full_auto=False,
        )
    )


def phase_timeout_seconds(config: LoopConfig, value: float | None) -> float | None:
    if value is None:
        return config.timeout_seconds
    if value == 0:
        return None
    return value


def ensure_model_budget(config: LoopConfig, *, phase: str, iteration: int | str, ctx: RunContext) -> None:
    if ctx.budget_state is None:
        return
    warning_due, elapsed = budgets.wall_warning_due(config.budget_config, ctx.budget_state)
    if warning_due:
        ctx.budget_state.wall_warning_emitted = True
        if ctx.event_sink is not None:
            ctx.event_sink.emit(
                "warning",
                phase=phase,
                iteration=iteration,
                payload={
                    "reason": "wall_budget_soft_warning",
                    "elapsed_wall_seconds": elapsed,
                    "max_wall_seconds": config.budget_config.max_wall_seconds,
                    "soft_warn_fraction": config.budget_config.soft_warn_fraction,
                },
            )
    try:
        budgets.check_wall_budget(config.budget_config, ctx.budget_state)
    except budgets.BudgetExceeded as exc:
        if ctx.event_sink is not None:
            ctx.event_sink.emit(
                "cost_ceiling_hit",
                phase=phase,
                iteration=iteration,
                payload={
                    "ceiling": exc.ceiling,
                    "limit": exc.limit,
                    "actual": exc.actual,
                    "message": str(exc),
                },
            )
        raise


def remaining_wall_budget_seconds(config: LoopConfig, ctx: RunContext) -> float | None:
    if (
        ctx.budget_state is None
        or config.budget_config.max_wall_seconds is None
    ):
        return None
    elapsed = budgets.wall_elapsed_seconds(ctx.budget_state)
    return max(0.0, config.budget_config.max_wall_seconds - elapsed)


def record_model_charge(
    config: LoopConfig,
    result: CommandResult,
    *,
    phase: str,
    iteration: int | str,
    ctx: RunContext,
) -> None:
    if ctx.budget_state is None:
        return
    if result.tokens is None and result.usd is None:
        return
    payload: dict[str, object] = {
        "tokens": result.tokens,
        "usd": str(result.usd) if result.usd is not None else None,
    }
    if ctx.event_sink is not None:
        ctx.event_sink.emit("cost_charge", phase=phase, iteration=iteration, payload=payload)
    try:
        budgets.record_charge(
            config.budget_config,
            ctx.budget_state,
            tokens=result.tokens,
            usd=result.usd,
        )
    except budgets.BudgetExceeded as exc:
        if ctx.event_sink is not None:
            ctx.event_sink.emit(
                "cost_ceiling_hit",
                phase=phase,
                iteration=iteration,
                payload={
                    "ceiling": exc.ceiling,
                    "limit": exc.limit,
                    "actual": exc.actual,
                    "message": str(exc),
                },
            )
        raise


def write_artifact(path: Path, content: str) -> None:
    artifacts.write_text_artifact(path, content)


# Checks implementation helpers. These remain imported here only where the
# runner still has direct callers; new code should import their adapter module
# homes directly.
from code_review_loop.adapters._checks_impl import (
    NON_PYTHON_PROJECT_MARKERS as NON_PYTHON_PROJECT_MARKERS,
)
from code_review_loop.adapters._checks_impl import (
    PYTHON_PROJECT_MARKERS as PYTHON_PROJECT_MARKERS,
)
from code_review_loop.adapters._checks_impl import (
    PYTHON_SCAN_SKIP_DIRS as PYTHON_SCAN_SKIP_DIRS,
)
from code_review_loop.adapters._checks_impl import (
    has_non_python_project_surface as has_non_python_project_surface,
)
from code_review_loop.adapters._checks_impl import (
    has_python_test_surface as has_python_test_surface,
)
from code_review_loop.adapters._checks_impl import (
    is_pytest_command as is_pytest_command,
)
from code_review_loop.adapters._checks_impl import (
    iter_project_files as iter_project_files,
)

# Commit-phase helpers used by the application runner while commit ownership
# continues moving behind CommitAdapter.
from code_review_loop.adapters._commit_impl import (
    classify_commit_failure as classify_commit_failure,
)
from code_review_loop.adapters._commit_impl import (
    commit_artifact_relative_path as commit_artifact_relative_path,
)
from code_review_loop.adapters._commit_impl import (
    commit_command_for_message as commit_command_for_message,
)
from code_review_loop.adapters._commit_impl import (
    commit_message_for_staged_changes as commit_message_for_staged_changes,
)
from code_review_loop.adapters._commit_impl import (
    deterministic_commit_message as deterministic_commit_message,
)
from code_review_loop.adapters._commit_impl import (
    format_commit_hook_failure_for_remediation as format_commit_hook_failure_for_remediation,
)
from code_review_loop.adapters._commit_impl import (
    git_repo_root as git_repo_root,
)
from code_review_loop.adapters._commit_impl import (
    git_worktree_status_command_for_commit as git_worktree_status_command_for_commit,
)

from code_review_loop.adapters._review_impl import (
    review_base_hint as review_base_hint,
)
from code_review_loop.adapters._review_impl import (
    review_base_preflight_error as review_base_preflight_error,
)
from code_review_loop.adapters._review_impl import (
    review_failed_to_run as review_failed_to_run,
)
from code_review_loop.adapters.git import run_git_preflight as run_git_preflight

CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\([A-Za-z0-9_.-]+\))?!?:\s+\S.+$"
)
REVREM_COMMIT_SUFFIX = " (RevRem)"
MAX_COMMIT_SUBJECT_LEN = 120


def sanitize_commit_message(
    output: str,
    *,
    fallback: str,
    enforce_revrem_conventional: bool = True,
) -> str:
    for raw_line in output.splitlines():
        line = raw_line.strip().strip("`\"'")
        if not line:
            continue
        line = re.sub(r"^commit message:\s*", "", line, flags=re.IGNORECASE).strip()
        line = line.strip("`\"'")
        if line:
            if enforce_revrem_conventional:
                return normalize_revrem_conventional_subject(line)
            return line[:120]
    return normalize_revrem_conventional_subject(fallback) if enforce_revrem_conventional else fallback


def normalize_revrem_conventional_subject(subject: str) -> str:
    subject = subject.strip().rstrip(".")
    subject = re.sub(r"\s+", " ", subject)
    subject = re.sub(r"\s+\(RevRem\)$", "", subject)
    if not CONVENTIONAL_COMMIT_RE.match(subject):
        subject = f"chore: {subject}"
    max_base_len = MAX_COMMIT_SUBJECT_LEN - len(REVREM_COMMIT_SUFFIX)
    if len(subject) > max_base_len:
        subject = subject[:max_base_len].rstrip()
    return f"{subject}{REVREM_COMMIT_SUFFIX}"


# Check failure formatting used by the application runner.
from code_review_loop.adapters._checks_impl import format_check_failures as _format_check_failures


def excerpt_for_terminal(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    return prompts_composer.trim_for_prompt(text, max_chars)


def add_artifact_paths(summary: dict[str, object], config: LoopConfig) -> None:
    artifact_dir = config.artifact_dir
    files = sorted(
        (path for path in artifact_dir.glob("*") if path.is_file()),
        key=artifact_sort_key,
    )
    summary["artifact_paths"] = {
        "artifact_dir": str(artifact_dir),
        "summary": str(artifact_dir / "summary.json"),
        "reviews": [
            str(path)
            for path in files
            if path.name.startswith("review-") and path.suffix == ".txt"
        ],
        "remediations": [
            str(path)
            for path in files
            if path.name.startswith("remediation-")
            and "last-message" not in path.name
            and not path.name.endswith("-prompt.txt")
        ],
        "prompts": [
            str(path)
            for path in files
            if path.name.startswith("remediation-") and path.name.endswith("-prompt.txt")
        ],
        "routing": [str(path) for path in files if path.name.startswith("routing-")],
        "triage": [str(path) for path in files if path.name.startswith("triage-")],
        "commits": [str(path) for path in files if path.name.startswith("commit-")],
        "last_messages": [
            str(path)
            for path in files
            if path.name.startswith("remediation-") and "last-message" in path.name
        ],
        "checks": [str(path) for path in files if path.name.startswith("check-")],
        "diagnostics": [
            str(path)
            for path in files
            if path.name == "diagnostics.json"
            or path.name.endswith("-status.json")
            or path.name.startswith("diagnostics-")
        ],
    }


def artifact_sort_key(path: Path) -> tuple[str, int, str]:
    name = path.name
    match = re.search(r"-(\d+)(?:-|\.txt$)", name)
    if match:
        return (name.split("-", 1)[0], int(match.group(1)), name)
    if "initial" in name:
        return (name.split("-", 1)[0], 0, name)
    if "final" in name:
        return (name.split("-", 1)[0], 1_000_000, name)
    return (name.split("-", 1)[0], 999_999, name)


def resolve_initial_review_file(value: str | None, search_root: Path) -> Path | None:
    if value is None:
        return None
    if value != "latest":
        return Path(value)

    candidates = sorted(
        (
            path
            for path in (
                search_root / "review-final.txt",
                *search_root.glob("*/review-final.txt"),
            )
            if path.is_file() and review_final_is_usable(path)
        ),
        key=lambda path: (path.stat().st_mtime, path.parent.name),
    )
    if not candidates:
        return None
    latest = candidates[-1]
    if review_final_is_resolved(latest):
        return None
    return latest


def review_final_is_resolved(review_path: Path) -> bool:
    summary_path = review_path.with_name("summary.json")
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(summary, dict) and summary.get("final_status") == "clear"


def review_final_is_usable(review_path: Path) -> bool:
    try:
        review_text = actionable_review_output(review_path.read_text(encoding="utf-8")).strip()
    except OSError:
        return False
    if not review_text:
        return False
    return not review_text.startswith("DRY_RUN")


def _config_snapshot(config: LoopConfig) -> ConfigSnapshot:
    return ConfigSnapshot(
        max_iterations=config.max_iterations,
        triage_enabled=config.triage_enabled,
        commit_after_remediation=config.commit_after_remediation,
        commit_on_hook_failure=config.commit_on_hook_failure,
        final_review=config.final_review,
    )


def _execute_stop(
    outcome: RunOutcome,
    state: RunState,
    summary: dict[str, object],
    config: LoopConfig,
    clock: Clock,
    ctx: RunContext,
    *,
    last_review_output: str = "",
    cause: BaseException | None = None,
) -> dict[str, object]:
    """Apply a Stop outcome to RunState, write summary, return or raise."""
    excerpt = (
        excerpt_for_terminal(last_review_output, config.terminal_excerpt_chars)
        if last_review_output
        else ""
    )

    def apply_common_tail(*, check_failures: bool = False) -> None:
        state.mark_outcome(outcome, excerpt=excerpt, check_failures=check_failures)
        summary.clear()
        summary.update(state.to_dict())
        write_summary(
            config,
            summary,
            clock=clock,
            budget_state=ctx.budget_state,
            event_sink=ctx.event_sink,
        )

    if isinstance(outcome, OutcomeClear):
        apply_common_tail()
        return summary

    if isinstance(outcome, OutcomeFailed):
        apply_common_tail(check_failures=outcome.check_failures)
        raise RunLoopFailed(summary, outcome.error, outcome=outcome) from cause

    if isinstance(outcome, OutcomeFindings):
        apply_common_tail(check_failures=outcome.check_failures)
        return summary

    if isinstance(outcome, OutcomeUnknown):
        apply_common_tail(check_failures=outcome.check_failures)
        return summary

    assert_never(outcome)


def _build_routing_payload(
    *,
    resolved_route: policy.ResolvedRoute,
    triage_payload: dict[str, Any],
    run_id: str,
    iteration: int,
    remediation_input: str,
    config: LoopConfig,
) -> dict[str, Any]:
    """Assemble the per-iteration routing decision artifact.

    Extracted from the inline ``_run_loop`` body in Wave C2b (TD-004). Pure with
    respect to the loop state: every input is passed explicitly so future
    callers (e.g. snapshot replay) can reconstruct the same artifact without
    re-running the policy resolver.
    """
    eff_harness = resolved_route.harness
    eff_model = resolved_route.model or config.remediation_model or config.model
    eff_reasoning = (
        resolved_route.reasoning_effort
        or config.remediation_reasoning_effort
        or config.reasoning_effort
    )
    eff_sandbox = resolved_route.sandbox
    eff_timeout = (
        int(resolved_route.timeout_seconds)
        if resolved_route.timeout_seconds is not None
        else 300
    )

    effective_route: dict[str, Any] = {
        "route_tier": resolved_route.route_tier,
        "harness": eff_harness,
        "sandbox": eff_sandbox,
        "timeout_seconds": eff_timeout,
    }
    if eff_model:
        effective_route["model"] = eff_model
    if eff_reasoning:
        effective_route["reasoning_effort"] = eff_reasoning

    proposal_present = bool(triage_payload.get("route_proposal"))
    proposal_matches_effective = False
    proposal_overrides: list[str] = []
    proposed_fields: dict[str, Any] = {}
    if proposal_present:
        p = triage_payload["route_proposal"]
        proposed_fields = {
            k: p[k]
            for k in (
                "route_tier",
                "harness",
                "model",
                "reasoning_effort",
                "sandbox",
                "timeout_seconds",
                "rationale",
            )
            if k in p
        }
        comparable_keys = (
            "route_tier",
            "harness",
            "model",
            "reasoning_effort",
            "sandbox",
            "timeout_seconds",
        )
        proposal_overrides = [
            key
            for key in comparable_keys
            if key in proposed_fields and effective_route.get(key) != proposed_fields[key]
        ]
        proposal_matches_effective = not proposal_overrides

    if resolved_route.fallback_applied:
        decision = "fallback_applied"
        original = (
            resolved_route.fallbacks_considered[0]
            if resolved_route.fallbacks_considered
            else "unknown"
        )
        rationale = f"Original route {original!r} fell back to {resolved_route.fallback_applied!r}."
    elif proposal_present and proposal_matches_effective:
        decision = "proposal_accepted"
        rationale = "Model route proposal accepted by policy."
    elif proposal_present:
        decision = "policy_override"
        if proposal_overrides:
            fields = ", ".join(proposal_overrides)
            rationale = (
                "Policy selected the proposed tier but overrode "
                f"proposal field(s): {fields}."
            )
        else:
            rationale = "Policy overrode the model route proposal."
    elif resolved_route.rule_id == "default":
        decision = "default_route_applied"
        rationale = "No model route proposal or rule match; applied default route."
    else:
        decision = "policy_override"
        rationale = "Applied policy based on classification."

    routing_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "iteration": iteration,
        "source_triage_artifact": f"triage-{iteration}.json",
        "policy_decision": {
            "decision": decision,
            "matched_rule_ids": (
                [resolved_route.rule_id]
                if resolved_route.rule_id and resolved_route.rule_id != "default"
                else []
            ),
            "rationale": rationale,
        },
        "effective_route": effective_route,
        "fallbacks_considered": list(resolved_route.fallbacks_considered),
        "prompt": {
            "path": f"remediation-{iteration}-prompt.txt",
            "sha256": prompts_composer.compute_prompt_hash(remediation_input),
            "bytes": len(remediation_input),
            "fragments": list(resolved_route.prompt_fragments),
        },
    }
    if proposal_present:
        routing_payload["model_proposal"] = proposed_fields
    return routing_payload


def run_loop(
    config: LoopConfig,
    runner: Runner = default_runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
) -> dict[str, object]:
    with (
        terminal_recovery_context(),
        terminal_title_context(config),
        progress_warning_context(),
        progress.rich_live_progress(config.progress and config.progress_style == "rich"),
    ):
        return _run_session(config, runner, clock=clock, identity=identity, budget_state=budget_state)


def resume_run(run_dir: Path) -> dict[str, object]:
    from code_review_loop import resume

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("summary.json must contain a JSON object")
    budget_issues = resume.resume_budget_ceiling_issues(summary)
    if budget_issues:
        raise ValueError("; ".join(issue.message for issue in budget_issues))
    config, resumed_budget_state = resume.resume_loop_config(summary, run_dir=run_dir)
    return run_loop(config, budget_state=resumed_budget_state)


class _RunSetup(NamedTuple):
    state: RunState
    summary: dict[str, object]
    event_sink: events.JsonlSink
    ctx: RunContext
    run_id: str


class _IterationStep(NamedTuple):
    acc: LoopAccumulator
    pending_check_failures: str
    failed_check_names: list[str]
    commit_retry: bool


class _IterationRun(NamedTuple):
    acc: LoopAccumulator
    pending_check_failures: str
    result: dict[str, object] | None


class _EngineDecision(NamedTuple):
    outcome: RunOutcome | None
    action: Continue | RetryViaCommitHook | None


def _engine_decision(
    snap: ConfigSnapshot,
    acc: LoopAccumulator,
    event: PhaseEvent,
    *,
    iteration: int = 1,
) -> _EngineDecision:
    action: Action = decide_engine(snap, acc, event, iteration=iteration)
    if isinstance(action, (Continue, RetryViaCommitHook)):
        return _EngineDecision(None, action)
    return _EngineDecision(action.outcome, None)


def _check_commit_cleanliness(config: LoopConfig, runner: Runner) -> None:
    if not config.commit_after_remediation or config.dry_run:
        return
    status_result = runner(
        git_worktree_status_command_for_commit(config),
        config.cwd,
        None,
        phase_timeout_seconds(config, config.timeout_seconds),
    )
    if status_result.returncode != 0:
        raise RuntimeError("git worktree status check failed before auto-commit could start")
    dirty_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    if dirty_lines:
        dirty_worktree = "\n".join(dirty_lines)
        raise RuntimeError(
            "refusing to enable --commit-after-remediation in a dirty worktree; "
            "clean the checkout or pass --no-commit-after-remediation.\n"
            f"Dirty paths:\n{dirty_worktree}"
        )


def _archive_existing_events(config: LoopConfig) -> None:
    events_path = config.artifact_dir / events.EVENTS_FILENAME
    if not events_path.is_file():
        return
    existing_run_id = events.first_run_id(events_path)
    if existing_run_id is not None:
        events_path.rename(events_path.with_name(f"events-{existing_run_id}.jsonl"))


def _create_progress_reporter(config: LoopConfig) -> ProgressReporter | None:
    from code_review_loop.adapters.terminal import TerminalProgressReporter

    if config.progress and config.progress_style in ("rich", "compact"):
        return TerminalProgressReporter(config.progress_style)
    return None


def _create_run_context(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock,
    identity: RunIdentity,
    event_sink: events.JsonlSink,
    budget_state: budgets.BudgetState | None,
) -> RunContext:
    from code_review_loop.adapters.checks import ChecksAdapter
    from code_review_loop.adapters.commit import CommitAdapter
    from code_review_loop.adapters.remediation import RemediationAdapter
    from code_review_loop.adapters.review import ReviewAdapter
    from code_review_loop.adapters.triage import TriageAdapter

    active_budget_state = budget_state if budget_state is not None else budgets.started_now()
    return RunContext(
        clock=clock,
        identity=identity,
        runner=cast(ProcessRunner, runner),
        event_sink=event_sink,
        budget_state=active_budget_state,
        progress_reporter=_create_progress_reporter(config),
        phase_checks=ChecksAdapter(config),
        phase_commit=CommitAdapter(config),
        phase_remediation=RemediationAdapter(config),
        phase_review=ReviewAdapter(config),
        phase_triage=TriageAdapter(config),
    )


def _prepare_run(
    config: LoopConfig,
    runner: Runner,
    *,
    clock: Clock,
    identity: RunIdentity,
    budget_state: budgets.BudgetState | None,
) -> _RunSetup:
    _check_commit_cleanliness(config, runner)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_artifact_ignore(config)
    run_id = identity.new_run_id()
    state = RunState.create(
        base=config.base,
        git_state=git_state_for_resume(config),
        resume_config=resume_config_payload(config),
        run_id=run_id,
        started_at=utc_iso(clock.now()),
        profile=config.profile_name,
        max_iterations=config.max_iterations,
        artifact_dir=str(config.artifact_dir),
        commit_on_hook_failure=config.commit_on_hook_failure,
        budgets=summary_budget_payload(config),
        initial_review_file=str(config.initial_review_file) if config.initial_review_file else None,
    )
    _archive_existing_events(config)
    event_sink = events.JsonlSink(config.artifact_dir, run_id, clock=clock)
    ctx = _create_run_context(
        config,
        runner,
        clock=clock,
        identity=identity,
        event_sink=event_sink,
        budget_state=budget_state,
    )
    return _RunSetup(state, state.to_dict(), event_sink, ctx, run_id)


def _profile_routed_harnesses(profile: profiles.Profile) -> tuple[str, ...]:
    if not profile.triage.enabled or not profile.triage.routing.enabled:
        return ()
    return tuple(route.harness for route in profile.triage.routes.values())


def _run_preflight(
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    *,
    clock: Clock,
    ctx: RunContext,
) -> dict[str, object] | None:
    if not config.preflight_enabled or config.dry_run:
        return None
    issues = diagnostics.run_doctor(
        diagnostics.DoctorConfig(
            cwd=config.cwd,
            base=config.base,
            artifact_dir=config.artifact_dir,
            artifact_dir_is_default=config.artifact_dir_is_default,
            codex_bin=config.codex_bin,
            review_harness=config.review_harness,
            remediation_harness=config.remediation_harness,
            triage_enabled=config.triage_enabled,
            triage_harness=config.triage_harness,
            commit_message_harness=config.commit_message_harness,
            routed_harnesses=(
                _profile_routed_harnesses(config.profile_v2)
                if config.profile_v2 is not None
                else ()
            ),
            harness_executables=config.harness_executables,
            check_commands=config.check_commands,
            commit_after_remediation=config.commit_after_remediation,
            timeout_seconds=config.timeout_seconds,
            review_timeout_seconds=config.review_timeout_seconds,
            remediation_timeout_seconds=config.remediation_timeout_seconds,
            triage_timeout_seconds=config.triage_timeout_seconds,
        )
    )
    if not diagnostics.has_blocking_issue(issues):
        return None
    artifacts.write_json_artifact(
        config.artifact_dir,
        "diagnostics.json",
        diagnostics.doctor_payload(issues),
    )
    emit_loop_failure_event(
        config,
        phase="preflight",
        iteration=None,
        reason="setup_failed",
        error="preflight diagnostics found blocking issue",
        ctx=ctx,
    )
    return _execute_stop(
        OutcomeFailed(reason="setup_failed", error="preflight diagnostics found blocking issue"),
        state, summary, config, clock, ctx,
    )


def _run_final_review(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    snap: ConfigSnapshot,
    acc: LoopAccumulator,
) -> dict[str, object]:
    if config.final_review:
        try:
            final_outcome = ctx.phase_review.execute(
                ReviewRequest(artifact_label="review-final", display_label="final"),
                ctx,
            )
            status, final_review = final_outcome.status, final_outcome.result
        except RuntimeError as exc:
            state.iterations.append({"iteration": "final", "review_failed": True})
            emit_loop_failure_event(
                config,
                phase="review",
                iteration="final",
                reason="review_failed",
                error=str(exc),
                ctx=ctx,
            )
            decision = _engine_decision(snap, acc, ReviewDone(is_final=True, status="unknown", exc=exc))
            assert decision.outcome is not None
            return _execute_stop(decision.outcome, state, summary, config, clock, ctx, cause=exc)
        final_review_output = actionable_review_output(_combined_output(final_review))
        acc = replace(acc, last_review_status=cast("Literal['clear', 'findings', 'unknown']", status))
        final_decision = _engine_decision(
            snap,
            acc,
            ReviewDone(is_final=True, status=cast("Literal['clear', 'findings', 'unknown']", status)),
        )
        assert final_decision.outcome is not None
        if status == "unknown" and not acc.pending_check_failures:
            state.iterations.append({"iteration": "final", "review_status": status})
        return _execute_stop(
            final_decision.outcome,
            state,
            summary,
            config,
            clock,
            ctx,
            last_review_output=final_review_output,
        )

    no_final_decision = _engine_decision(snap, acc, NoFinalReview())
    assert no_final_decision.outcome is not None
    return _execute_stop(no_final_decision.outcome, state, summary, config, clock, ctx)


def _run_iteration(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    snap: ConfigSnapshot,
    acc: LoopAccumulator,
    iteration: int,
    pending_check_failures: str,
    failed_check_names: list[str],
    commit_retry: bool,
    initial_review_output: str,
    run_id: str,
) -> dict[str, object] | _IterationStep:
    iterations = state.iterations
    acc = replace(acc, pending_check_failures=pending_check_failures)
    if iteration == 1 and initial_review_output:
        status = detect_review_status(initial_review_output)
        if status == "unknown":
            status = "findings"
        last_review_output = initial_review_output
        iterations.append(
            {
                "iteration": iteration,
                "review_status": status,
                "review_source": str(config.initial_review_file),
            }
        )
        acc = replace(acc, last_review_status=cast("Literal['clear', 'findings', 'unknown']", status))
    else:
        try:
            review_outcome = ctx.phase_review.execute(
                ReviewRequest(artifact_label=f"review-{iteration}", display_label=str(iteration)),
                ctx,
            )
            status, review = review_outcome.status, review_outcome.result
        except RuntimeError as exc:
            iterations.append({"iteration": iteration, "review_failed": True})
            emit_loop_failure_event(
                config,
                phase="review",
                iteration=iteration,
                reason="review_failed",
                error=str(exc),
                ctx=ctx,
            )
            decision = _engine_decision(snap, acc, ReviewDone(is_final=False, status="unknown", exc=exc))
            assert decision.outcome is not None
            return _execute_stop(decision.outcome, state, summary, config, clock, ctx, cause=exc)
        last_review_output = actionable_review_output(_combined_output(review))
        iterations.append({"iteration": iteration, "review_status": status})
        acc = replace(acc, last_review_status=cast("Literal['clear', 'findings', 'unknown']", status))

    review_decision = _engine_decision(
        snap,
        acc,
        ReviewDone(is_final=False, status=cast("Literal['clear', 'findings', 'unknown']", status)),
    )
    if review_decision.outcome is not None:
        return _execute_stop(
            review_decision.outcome,
            state,
            summary,
            config,
            clock,
            ctx,
            last_review_output=last_review_output,
        )

    remediation_input = last_review_output
    if pending_check_failures:
        remediation_input = pending_check_failures + "\n\n" + remediation_input
    try:
        resolved_route = None
        if config.triage_enabled:
            source_review_artifact = (
                "review-initial.txt" if iteration == 1 and initial_review_output else f"review-{iteration}.txt"
            )
            triage_outcome = ctx.phase_triage.execute(
                TriageRequest(
                    iteration=iteration,
                    run_id=run_id,
                    source_review_artifact=source_review_artifact,
                    review_output=remediation_input,
                ),
                ctx,
            )
            remediation_input = triage_outcome.handoff
            suppressed_count = triage_outcome.suppressed_count
            triage_no_actionable = triage_outcome.is_clear
            triage_payload = triage_outcome.payload
            if suppressed_count:
                iterations[-1]["suppressed_findings_count"] = suppressed_count
            if triage_no_actionable:
                if suppressed_count:
                    iterations[-1]["suppressed_findings"] = True
                    state.set_suppressed_findings_count(suppressed_count)
                triage_decision = _engine_decision(snap, acc, TriageDone(is_clear=True, suppressed_count=suppressed_count))
                if triage_decision.outcome is not None:
                    iterations[-1]["check_failures"] = 0
                    return _execute_stop(
                        triage_decision.outcome,
                        state,
                        summary,
                        config,
                        clock,
                        ctx,
                        last_review_output=last_review_output,
                    )
                remediation_input = pending_check_failures

            if triage_payload and config.triage_contract == "v2" and config.profile_v2:
                routing_config = config.profile_v2.triage.routing
                if routing_config.enabled:
                    routing_context = triage.extract_routing_context(
                        triage_payload,
                        config.cwd,
                        failed_checks=tuple(failed_check_names),
                    )
                    model_proposal = triage_payload.get("route_proposal", {})
                    resolved_route = policy.resolve_routing(
                        config.profile_v2,
                        routing_context,
                        model_proposal_tier=model_proposal.get("route_tier"),
                        max_timeout_seconds=remaining_wall_budget_seconds(config, ctx),
                    )
                    progress_event(
                        config,
                        "triage",
                        str(iteration),
                        "routing",
                        f"routed to {resolved_route.route_tier} ({resolved_route.harness})",
                        ctx=ctx,
                    )
                else:
                    resolved_route = policy.ResolvedRoute(
                        route_tier="default",
                        harness=config.remediation_harness,
                        model=config.remediation_model or config.model,
                        reasoning_effort=config.remediation_reasoning_effort
                        or config.reasoning_effort,
                        timeout_seconds=config.remediation_timeout_seconds,
                        sandbox=config.exec_sandbox,
                        prompt_fragments=(),
                        allow_model_deescalation=True,
                        rule_id="default",
                    )

                remediation_input = prompts_composer.compose_remediation_prompt(
                    config.cwd,
                    triage_payload,
                    resolved_route,
                    remediation_input,
                    max_chars=config.max_remediation_input_chars,
                    trusted_repo=config.trusted_repo,
                )
                routing_payload = _build_routing_payload(
                    resolved_route=resolved_route,
                    triage_payload=triage_payload,
                    run_id=run_id,
                    iteration=iteration,
                    remediation_input=remediation_input,
                    config=config,
                )
                try:
                    triage.validate_routing_payload(routing_payload)
                except triage.TriageValidationError as exc:
                    issue = triage.invalid_triage_issue(exc, iteration=iteration)
                    artifacts.write_json_artifact(
                        config.artifact_dir,
                        f"diagnostics-{iteration}.json",
                        diagnostics.doctor_payload([issue]),
                    )
                    progress_event(
                        config,
                        "triage",
                        str(iteration),
                        "invalid",
                        f"routing payload schema validation failed: {exc}",
                        ctx=ctx,
                    )
                    raise RuntimeError(f"invalid routing decision artifact for iteration {iteration}: {exc}") from exc

                triage.write_routing_artifact(config.artifact_dir, iteration, routing_payload)
                if ctx.event_sink:
                    ctx.event_sink.emit("routing_decision", phase="triage", iteration=iteration, payload=routing_payload)
                write_artifact(config.artifact_dir / f"remediation-{iteration}-prompt.txt", remediation_input)
    except budgets.BudgetExceeded:
        raise
    except Exception as exc:
        iterations[-1]["triage_failed"] = True
        emit_loop_failure_event(
            config,
            phase="triage",
            iteration=iteration,
            reason="triage_failed",
            error=str(exc),
            ctx=ctx,
        )
        decision = _engine_decision(snap, acc, TriageDone(is_clear=False, exc=exc))
        assert decision.outcome is not None
        return _execute_stop(decision.outcome, state, summary, config, clock, ctx, cause=exc)

    try:
        rem_start_time = clock.monotonic()
        rem_outcome = ctx.phase_remediation.execute(
            RemediationRequest(iteration=iteration, remediation_input=remediation_input, resolved_route=resolved_route),
            ctx,
        )
        rem_result = rem_outcome.result
        rem_duration = clock.monotonic() - rem_start_time
    except budgets.BudgetExceeded:
        raise
    except Exception as exc:
        iterations[-1]["remediation_failed"] = True
        emit_loop_failure_event(
            config,
            phase="remediate",
            iteration=iteration,
            reason="remediation_failed",
            error=str(exc),
            ctx=ctx,
        )
        decision = _engine_decision(snap, acc, RemediationDone(exc=exc))
        assert decision.outcome is not None
        return _execute_stop(decision.outcome, state, summary, config, clock, ctx, cause=exc)

    checks_outcome = ctx.phase_checks.execute(ChecksRequest(iteration=iteration), ctx)
    check_results = list(checks_outcome.results)
    failed_check_names = list(checks_outcome.failed_commands)
    pending_check_failures = _format_check_failures(check_results)
    state.set_pending_check_failures(bool(pending_check_failures))
    iterations[-1]["check_failures"] = len(failed_check_names)
    if resolved_route:
        outcome_payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "iteration": iteration,
            "source_routing_artifact": f"routing-{iteration}.json",
            "exit_code": rem_result.returncode,
            "wall_time_seconds": round(rem_duration, 3),
            "checks_passed": all(r.returncode == 0 for r in check_results),
        }
        triage.write_routing_outcome_artifact(config.artifact_dir, iteration, outcome_payload)
        if ctx.event_sink:
            ctx.event_sink.emit("routing_outcome", phase="remediate", iteration=iteration, payload=outcome_payload)
    if config.commit_after_remediation and not pending_check_failures:
        try:
            commit_outcome = ctx.phase_commit.execute(CommitRequest(iteration=iteration, retrying=commit_retry), ctx)
            iterations[-1]["commit_status"] = commit_outcome.status
        except CommitFailed as exc:
            iterations[-1]["commit_status"] = exc.kind
            iterations[-1]["commit_failed"] = True
            iterations[-1]["commit_artifact"] = str(exc.artifact_path)
            commit_decision = _engine_decision(
                snap,
                acc,
                CommitDone(status=exc.kind, commit_failed=exc),
                iteration=iteration,
            )
            if isinstance(commit_decision.action, RetryViaCommitHook):
                pending_check_failures = format_commit_hook_failure_for_remediation(exc)
                acc = replace(acc, commit_retry=True, pending_check_failures=pending_check_failures)
                state.set_pending_check_failures(True)
                progress_event(
                    config,
                    "commit",
                    str(iteration),
                    "retry",
                    "hook output will feed next remediation",
                    ctx=ctx,
                )
                return _IterationStep(acc, pending_check_failures, failed_check_names, True)
            assert commit_decision.outcome is not None
            emit_loop_failure_event(
                config,
                phase="commit",
                iteration=iteration,
                reason=commit_decision.outcome.reason,
                error=str(exc),
                ctx=ctx,
            )
            return _execute_stop(commit_decision.outcome, state, summary, config, clock, ctx, cause=exc)
        except budgets.BudgetExceeded:
            raise
        except Exception as exc:
            iterations[-1]["commit_failed"] = True
            emit_loop_failure_event(
                config,
                phase="commit",
                iteration=iteration,
                reason="commit_failed",
                error=str(exc),
                ctx=ctx,
            )
            decision = _engine_decision(
                snap,
                acc,
                CommitDone(status=None, other_exc=exc),
                iteration=iteration,
            )
            assert decision.outcome is not None
            return _execute_stop(decision.outcome, state, summary, config, clock, ctx, cause=exc)
        commit_decision = _engine_decision(
            snap,
            acc,
            CommitDone(status=cast("str | None", iterations[-1].get("commit_status"))),
            iteration=iteration,
        )
        if commit_decision.outcome is not None:
            return _execute_stop(
                commit_decision.outcome,
                state,
                summary,
                config,
                clock,
                ctx,
                last_review_output=last_review_output,
            )

    return _IterationStep(acc, pending_check_failures, failed_check_names, commit_retry)


def _load_initial_review(config: LoopConfig, ctx: RunContext) -> str:
    if config.initial_review_file is None:
        return ""
    initial_review_output = actionable_review_output(config.initial_review_file.read_text(encoding="utf-8"))
    write_artifact(config.artifact_dir / "review-initial.txt", initial_review_output + "\n")
    progress_event(config, "review", "initial", "loaded", str(config.initial_review_file), ctx=ctx)
    log_review_findings(config, "initial", initial_review_output, ctx=ctx)
    return initial_review_output


def _finish_cancelled(
    exc: KeyboardInterrupt,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> dict[str, object]:
    artifacts.write_json_artifact(
        config.artifact_dir,
        "diagnostics.json",
        diagnostics.doctor_payload(
            [
                diagnostics.DiagnosticIssue(
                    code="revrem.run.cancelled",
                    severity="blocking",
                    message="RevRem run was cancelled by the operator.",
                    hint="Inspect summary.json and events.jsonl to determine the last completed phase before resuming or rerunning.",
                    evidence={"reason": "operator_interrupt"},
                )
            ]
        ),
    )
    if ctx.event_sink is not None:
        ctx.event_sink.emit(
            "cancellation",
            phase="run",
            payload={
                "reason": "operator_interrupt",
                "message": "cancelled by operator",
            },
        )
    return _execute_stop(
        OutcomeFailed(reason="cancelled", error="cancelled by operator"),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )


def _finish_budget_exceeded(
    exc: budgets.BudgetExceeded,
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
) -> dict[str, object]:
    return _execute_stop(
        OutcomeFailed(reason="budget_ceiling_hit", error=str(exc)),
        state,
        summary,
        config,
        clock,
        ctx,
        cause=exc,
    )


def _run_iterations(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    snap: ConfigSnapshot,
    initial_review_output: str,
    run_id: str,
) -> _IterationRun:
    acc = LoopAccumulator(pending_check_failures="")
    pending_check_failures = ""
    failed_check_names: list[str] = []
    commit_retry = False

    for iteration in range(1, config.max_iterations + 1):
        step = _run_iteration(
            config=config,
            state=state,
            summary=summary,
            clock=clock,
            ctx=ctx,
            snap=snap,
            acc=acc,
            iteration=iteration,
            pending_check_failures=pending_check_failures,
            failed_check_names=failed_check_names,
            commit_retry=commit_retry,
            initial_review_output=initial_review_output,
            run_id=run_id,
        )
        if isinstance(step, dict):
            return _IterationRun(acc, pending_check_failures, step)
        acc = step.acc
        pending_check_failures = step.pending_check_failures
        failed_check_names = step.failed_check_names
        commit_retry = step.commit_retry

    return _IterationRun(acc, pending_check_failures, None)


def _run_session_body(
    *,
    config: LoopConfig,
    state: RunState,
    summary: dict[str, object],
    clock: Clock,
    ctx: RunContext,
    run_id: str,
) -> dict[str, object]:
    preflight_result = _run_preflight(config, state, summary, clock=clock, ctx=ctx)
    if preflight_result is not None:
        return preflight_result

    initial_review_output = _load_initial_review(config, ctx)
    snap = _config_snapshot(config)
    iterations = _run_iterations(
        config=config,
        state=state,
        summary=summary,
        clock=clock,
        ctx=ctx,
        snap=snap,
        initial_review_output=initial_review_output,
        run_id=run_id,
    )
    if iterations.result is not None:
        return iterations.result
    acc = replace(iterations.acc, pending_check_failures=iterations.pending_check_failures)
    return _run_final_review(
        config=config,
        state=state,
        summary=summary,
        clock=clock,
        ctx=ctx,
        snap=snap,
        acc=acc,
    )


def _run_session(
    config: LoopConfig,
    runner: Runner = default_runner,
    *,
    clock: Clock = SYSTEM_CLOCK,
    identity: RunIdentity = SYSTEM_IDENTITY,
    budget_state: budgets.BudgetState | None = None,
) -> dict[str, object]:
    if config.max_iterations < 1:
        raise ValueError("--max-iterations must be at least 1")

    setup = _prepare_run(config, runner, clock=clock, identity=identity, budget_state=budget_state)
    state = setup.state
    summary = setup.summary

    event_sink = setup.event_sink
    ctx = setup.ctx
    run_id = setup.run_id
    try:
        return _run_session_body(
            config=config,
            state=state,
            summary=summary,
            clock=clock,
            ctx=ctx,
            run_id=run_id,
        )
    except KeyboardInterrupt as exc:
        return _finish_cancelled(exc, config=config, state=state, summary=summary, clock=clock, ctx=ctx)
    except budgets.BudgetExceeded as exc:
        return _finish_budget_exceeded(exc, config=config, state=state, summary=summary, clock=clock, ctx=ctx)
    finally:
        event_sink.close()


def write_summary(
    config: LoopConfig,
    summary: dict[str, object],
    *,
    clock: Clock = SYSTEM_CLOCK,
    budget_state: budgets.BudgetState | None = None,
    event_sink: EventSink | None = None,
) -> None:
    update_unexpected_behaviors(config, summary)
    add_summary_contract_fields(config, summary, clock=clock)
    add_artifact_paths(summary, config)
    if budget_state is not None or "budgets" not in summary:
        summary["budgets"] = summary_budget_payload(config, budget_state=budget_state)
    if event_sink is not None:
        emit_artifact_write_events(config, summary, event_sink=event_sink)
        summary_detail = summary.get("stopped_reason") or summary.get("final_status") or "summary"
        event_sink.emit(
            "summary",
            payload={
                "summary": str(summary_detail),
            },
        )
    artifacts.write_json_artifact(config.artifact_dir, "summary.json", summary)


def git_state_for_resume(config: LoopConfig) -> dict[str, object]:
    if lexical_git_repo_root(config.cwd) is None:
        return {
            "head": None,
            "base": config.base,
            "base_commit": None,
            "merge_base": None,
            "available": False,
        }
    head = git_preflight_stdout(config.cwd, ["rev-parse", "HEAD"])
    base_commit = git_preflight_stdout(config.cwd, ["rev-parse", "--verify", f"{config.base}^{{commit}}"])
    merge_base = (
        git_preflight_stdout(config.cwd, ["merge-base", "HEAD", config.base])
        if base_commit is not None
        else None
    )
    return {
        "head": head,
        "base": config.base,
        "base_commit": base_commit,
        "merge_base": merge_base,
        "available": head is not None and base_commit is not None,
    }


def git_preflight_stdout(cwd: Path, args: Sequence[str]) -> str | None:
    result = run_git_preflight(cwd, args)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def resume_config_payload(config: LoopConfig) -> dict[str, object]:
    """Persist the loop inputs required to resume with the same safety envelope."""
    return {
        "base": config.base,
        "max_iterations": config.max_iterations,
        "codex_bin": config.codex_bin,
        "harness_executables": dict(config.harness_executables),
        "review_harness": config.review_harness,
        "remediation_harness": config.remediation_harness,
        "triage_harness": config.triage_harness,
        "review_model": config.review_model or config.model,
        "remediation_model": config.remediation_model or config.model,
        "triage_model": config.triage_model,
        "triage_enabled": config.triage_enabled,
        "final_review": config.final_review,
        "check_commands": list(config.check_commands),
        "timeout_seconds": config.timeout_seconds,
        "review_timeout_seconds": config.review_timeout_seconds,
        "remediation_timeout_seconds": config.remediation_timeout_seconds,
        "triage_timeout_seconds": config.triage_timeout_seconds,
        "progress_style": config.progress_style,
        "debug_status_detection": config.debug_status_detection,
        "terminal_excerpt_chars": config.terminal_excerpt_chars,
        "max_remediation_input_chars": config.max_remediation_input_chars,
        "commit_after_remediation": config.commit_after_remediation,
        "commit_on_hook_failure": config.commit_on_hook_failure,
        "exec_sandbox": config.exec_sandbox,
        "exec_json": config.exec_json,
        "output_last_message": config.output_last_message,
        "full_auto": config.full_auto,
        "max_wall_seconds": config.budget_config.max_wall_seconds,
        "max_tokens": config.budget_config.max_tokens,
        "max_usd": str(config.budget_config.max_usd) if config.budget_config.max_usd is not None else None,
        "soft_warn_fraction": config.budget_config.soft_warn_fraction,
        "triage_prompt": config.triage_prompt,
        "triage_on_invalid": config.triage_on_invalid,
        "triage_contract": config.triage_contract,
        "profile_name": config.profile_name,
    }


def summary_budget_payload(
    config: LoopConfig,
    *,
    budget_state: budgets.BudgetState | None = None,
) -> dict[str, object]:
    tokens = None
    usd = None
    wall_elapsed_seconds = None
    if budget_state is not None:
        wall_elapsed_seconds = budgets.wall_elapsed_seconds(budget_state)
        if budget_state.tokens_reported:
            tokens = budget_state.tokens_used
        if budget_state.usd_reported:
            usd = str(budget_state.usd_used)
    return {
        "max_wall_seconds": config.budget_config.max_wall_seconds,
        "max_tokens": config.budget_config.max_tokens,
        "max_usd": str(config.budget_config.max_usd) if config.budget_config.max_usd is not None else None,
        "soft_warn_fraction": config.budget_config.soft_warn_fraction,
        "wall_elapsed_seconds": wall_elapsed_seconds,
        "tokens": tokens,
        "usd": usd,
    }


def emit_artifact_write_events(config: LoopConfig, summary: dict[str, object], *, event_sink: EventSink) -> None:
    artifact_paths = summary.get("artifact_paths")
    if not isinstance(artifact_paths, dict):
        return
    for kind, path in iter_artifact_paths(artifact_paths):
        payload: dict[str, object] = {"kind": kind, "path": path}
        with suppress(OSError):
            payload["bytes"] = Path(path).stat().st_size
        event_sink.emit("artifact_write", phase="artifacts", payload=payload)


def iter_artifact_paths(artifact_paths: dict[object, object]) -> Iterator[tuple[str, str]]:
    for kind, value in artifact_paths.items():
        if kind == "artifact_dir":
            continue
        if isinstance(kind, str) and isinstance(value, str):
            yield kind, value
        elif isinstance(kind, str) and isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield kind, item


def add_summary_contract_fields(
    config: LoopConfig, summary: dict[str, object], *, clock: Clock = SYSTEM_CLOCK
) -> None:
    summary["schema_version"] = artifacts.JSON_SCHEMA_VERSION
    summary.setdefault("cli_version", __version__)
    summary.setdefault("harness", config.review_harness)
    summary.setdefault("harness_version", None)
    summary.setdefault("command_line", None)
    summary.setdefault("tokens", None)
    summary.setdefault("usd", None)
    iterations = summary.get("iterations")
    summary.setdefault(
        "phases",
        {
            "_summary": {
                "iteration_count": len(iterations) if isinstance(iterations, list) else 0,
            },
        },
    )
    summary.setdefault("finished_at", utc_iso(clock.now()))
    summary.setdefault("duration_seconds", _summary_duration_seconds(summary))


def _summary_duration_seconds(summary: dict[str, object]) -> float | None:
    started_at = summary.get("started_at")
    finished_at = summary.get("finished_at")
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())


def update_unexpected_behaviors(config: LoopConfig, summary: dict[str, object]) -> None:
    iterations = summary.get("iterations")
    if not isinstance(iterations, list):
        return
    unknowns = [
        item
        for item in iterations
        if isinstance(item, dict) and item.get("review_status") == "unknown"
    ]
    if not unknowns:
        summary.pop("unexpected_behaviors", None)
        summary.pop("bug_report_path", None)
        return

    report_path = config.artifact_dir / "unexpected-behavior-report.txt"
    behaviors: list[dict[str, object]] = []
    lines = [
        "RevRem unexpected behavior report",
        "",
        "A review status was classified as unknown during this run.",
        "Please include this file and the referenced review/status artifacts in a bug report.",
        "",
        f"run_id: {summary.get('run_id')}",
        f"base: {summary.get('base')}",
        f"final_status: {summary.get('final_status')}",
        f"stopped_reason: {summary.get('stopped_reason')}",
        f"artifact_dir: {summary.get('artifact_dir')}",
        "",
        "Unknown review iterations:",
    ]
    for item in unknowns:
        iteration = item.get("iteration")
        review_path = config.artifact_dir / f"review-{iteration}.txt"
        status_path = config.artifact_dir / f"review-{iteration}-status.json"
        behavior = {
            "kind": "unknown_review_status",
            "iteration": iteration,
            "review_path": str(review_path),
        }
        if status_path.is_file():
            behavior["status_diagnostics_path"] = str(status_path)
        behaviors.append(behavior)
        lines.append(f"- iteration {iteration}: {review_path}")
        if status_path.is_file():
            lines.append(f"  diagnostics: {status_path}")
    lines.append("")
    write_artifact(report_path, "\n".join(lines))
    summary["unexpected_behaviors"] = behaviors
    summary["bug_report_path"] = str(report_path)


def append_run_history(summary: dict[str, object], config: LoopConfig) -> Path:
    history_path = run_history.append_history(summary, cwd=config.cwd)
    summary["history_path"] = str(history_path)
    write_summary(config, summary)
    return history_path


def _combined_output(result: CommandResult) -> str:
    parts = []
    if result.stdout:
        parts.append(result.stdout.rstrip())
    if result.stderr:
        parts.append("\n[stderr]\n" + result.stderr.rstrip())
    return "\n".join(parts).strip() + "\n"


def git_info_exclude_path(cwd: Path) -> Path | None:
    git_path = cwd / ".git"
    if git_path.is_dir():
        return git_path / "info" / "exclude"
    if not git_path.is_file():
        return None
    content = git_path.read_text(encoding="utf-8", errors="replace").strip()
    if not content.startswith("gitdir:"):
        return None
    git_dir = Path(content.split(":", 1)[1].strip())
    if not git_dir.is_absolute():
        git_dir = git_path.parent / git_dir
    # Linked worktrees share the common repository's info/exclude file.
    if git_dir.parent.name == "worktrees":
        return git_dir.parent.parent / "info" / "exclude"
    return git_dir / "info" / "exclude"
