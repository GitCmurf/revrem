#!/usr/bin/env python3
"""Run a bounded Codex review/remediation loop against a base branch."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_review_loop import (
    __version__,
    artifacts,
    bug_bundle,
    diagnostics,
    events,
    harnesses,
    profiles,
    progress,
    run_history,
    suppressions,
    triage,
)

STATUS_RE = re.compile(r"^\s*REVIEW_STATUS:\s*(clear|findings)\s*$", re.IGNORECASE | re.MULTILINE)
CODEX_FINDING_RE = re.compile(r"^\s*-\s*\[P[0-3]\]\s+", re.MULTILINE)
CODEX_FINDING_LINE_RE = re.compile(r"^\s*-\s*(\[P[0-3]\]\s+.+)$")
REVIEW_COMMENTS_HEADING_RE = re.compile(
    r"^\s*(full\s+)?review comments?:\s*$",
    re.IGNORECASE | re.MULTILINE,
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
DEFAULT_TIMEOUT_SECONDS = 300
REASONING_EFFORT_CHOICES = ("minimal", "low", "medium", "high")
PROGRESS_STYLE_CHOICES = ("compact", "verbose", "rich")
COMMIT_ON_HOOK_FAILURE_CHOICES = profiles.COMMIT_ON_HOOK_FAILURE_CHOICES
COMMIT_HOOK_FAILURE_RE = re.compile(
    r"\b("
    r"pre-commit|pre-push|commit hook|hook failed|"
    r"mypy|ruff|black|flake8|eslint|prettier|detect-secrets|"
    r"files? were modified by this hook|found \d+ errors?"
    r")\b",
    re.IGNORECASE,
)

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


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class LoopConfig:
    base: str
    max_iterations: int
    codex_bin: str
    cwd: Path
    artifact_dir: Path
    model: str | None = None
    review_harness: str = "codex"
    remediation_harness: str = "codex"
    triage_harness: str = "codex"
    commit_message_harness: str = "codex"
    review_model: str | None = None
    remediation_model: str | None = None
    reasoning_effort: str | None = None
    review_reasoning_effort: str | None = None
    remediation_reasoning_effort: str | None = None
    commit_after_remediation: bool = False
    commit_message_model: str | None = None
    commit_message_prompt: str | None = None
    commit_message_prompt_overridden: bool = False
    commit_on_hook_failure: str = "remediate"
    commit_reasoning_effort: str | None = None
    triage_enabled: bool = False
    triage_model: str | None = None
    triage_reasoning_effort: str | None = None
    triage_timeout_seconds: float | None = None
    triage_prompt: str | None = None
    triage_on_invalid: str = "continue"
    suppressions_enabled: bool = True
    exec_sandbox: str = "workspace-write"
    exec_color: str = "never"
    full_auto: bool = True
    exec_json: bool = False
    output_last_message: bool = True
    dry_run: bool = False
    final_review: bool = True
    max_remediation_input_chars: int = 200_000
    terminal_excerpt_chars: int = 4_000
    timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS
    review_timeout_seconds: float | None = None
    remediation_timeout_seconds: float | None = None
    debug_status_detection: bool = False
    progress: bool = True
    progress_style: str = "compact"
    terminal_title: bool = False
    initial_review_file: Path | None = None
    check_commands: tuple[str, ...] = field(default_factory=tuple)
    profile_name: str | None = None


Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


class RunLoopFailed(RuntimeError):
    """Raised when a bounded loop finishes with an expected step failure."""

    def __init__(self, summary: dict[str, object], message: str):
        super().__init__(message)
        self.summary = summary


class CommitFailed(RuntimeError):
    """Raised when git commit fails after verified remediation staging."""

    def __init__(
        self,
        *,
        iteration: int,
        kind: str,
        artifact_path: Path,
        output: str,
    ):
        super().__init__(
            f"git commit failed for iteration {iteration}; see {artifact_path}"
        )
        self.iteration = iteration
        self.kind = kind
        self.artifact_path = artifact_path
        self.output = output

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
    previous_handlers: dict[signal.Signals, Any] = {}
    handled_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGTSTP"):
        handled_signals.append(signal.SIGTSTP)

    def handle_signal(signum: int, frame: object | None) -> None:
        restore_terminal_display()
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
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def progress_log(config: LoopConfig, message: str) -> None:
    if not config.progress:
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
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
    timestamp = datetime.now().strftime("%H:%M:%S")
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


def progress_event(config: LoopConfig, phase: str, label: str, status: str, detail: str = "") -> None:
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
            f"Command timed out after {timeout_seconds} seconds\n"
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
    deadline = None if timeout is None else time.monotonic() + timeout
    pending_input = input
    try:
        while True:
            refresh_terminal_title()
            wait = TERMINAL_TITLE_REFRESH_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
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
    """Kill a subprocess and descendants started in its process group."""
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


def detect_review_status(output: str) -> str:
    """Return clear/findings/unknown for Codex review output."""
    actionable_output = actionable_review_output(output)
    match = STATUS_RE.search(actionable_output)
    if match:
        return match.group(1).lower()

    structured_status = structured_review_status(actionable_output)
    if structured_status is not None:
        return structured_status

    if CODEX_FINDING_RE.search(actionable_output):
        return "findings"

    normalized = actionable_output.lower()
    finding_markers = (
        "review comment:",
        "review comments:",
        "full review comments:",
    )
    if any(marker in normalized for marker in finding_markers):
        return "findings"

    normalized_lines = [line.strip().lower() for line in actionable_output.splitlines()]
    clear_lines = {
        "no findings.",
        "no findings",
        "no issues found.",
        "no issues found",
        "no actionable findings.",
        "no actionable findings",
    }
    if any(line in clear_lines for line in normalized_lines):
        return "clear"
    if has_negated_clear_review_statement(normalized) and not has_affirmative_issue_prose(
        actionable_output
    ):
        return "clear"
    if any(phrase in normalized for phrase in CLEAR_PHRASES) and not has_affirmative_issue_prose(
        actionable_output
    ):
        return "clear"
    return "unknown"


def structured_review_status(output: str) -> str | None:
    """Classify Codex structured JSON review output when it exposes findings."""
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    findings = parsed.get("findings")
    if isinstance(findings, list):
        return "findings" if findings else "clear"
    return None


NEGATED_CLEAR_REVIEW_STATEMENT_RE = re.compile(
    r"(?:^|[.!?,;]\s+|,\s+and\s+|and\s+)(?:i\s+)?did not (?:identify|find) "
    r"(?:any(?: discrete(?: introduced)?)?|a discrete(?: introduced)?)\b"
    r"[^.!?]*(?:issue|issues|bug|bugs|defect|defects|regression|regressions|finding|findings|correctness|security|maintainability)"
)


def has_negated_clear_review_statement(normalized: str) -> bool:
    return NEGATED_CLEAR_REVIEW_STATEMENT_RE.search(normalized) is not None


AFFIRMATIVE_ISSUE_WORD_RE = re.compile(
    r"\b(?:bug|bugs|issue|issues|regression|regressions|defect|defects|problem|problems|"
    r"failure|failures|finding|findings)\b",
    re.IGNORECASE,
)
STRUCTURED_EMPTY_FINDINGS_RE = re.compile(
    r'(?<!\w)["\']?findings["\']?\s*:\s*\[\s*\](?!\w)',
    re.IGNORECASE,
)

NEGATED_ISSUE_PREFIX_RE = r"(?:clear|discrete|actionable|introduced|known|new|obvious|blocking|material|major|serious|outstanding|significant|additional|further|remaining|open|critical|severe|real|actual|genuine|substantive|meaningful|correctness|security|maintainability)"
NEGATED_ISSUE_PREFIX_CHAIN_RE = rf"{NEGATED_ISSUE_PREFIX_RE}(?:[\s,;:-]+{NEGATED_ISSUE_PREFIX_RE})*"
NEGATED_ISSUE_WORD_RE = r"(?:bug|bugs|issue|issues|regression|regressions|defect|defects|problem|problems|failure|failures|finding|findings)"
NEGATED_ISSUE_PROSE_RE = re.compile(
    rf"\b(?:"
    rf"no(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|without(?:\s+any)?(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|without\s+revealing(?:\s+any)?(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|(?:did|does|do)\s+not\s+"
    rf"(?:find|identify|detect|see|spot|surface|observe|notice)\s+"
    rf"(?:any\s+)?(?:{NEGATED_ISSUE_PREFIX_CHAIN_RE}\s+)?{NEGATED_ISSUE_WORD_RE}\b"
    rf"|(?:didn't|doesn't|don't|cannot|can't)\s+"
    rf"(?:find|identify|detect|see|spot|surface|observe|notice)\s+"
    rf"(?:any\s+)?(?:{NEGATED_ISSUE_PREFIX_CHAIN_RE}\s+)?{NEGATED_ISSUE_WORD_RE}\b"
    rf")",
    re.IGNORECASE,
)
CONTRASTIVE_CLAUSE_RE = re.compile(r"\b(?:but|however|though|although|yet|nevertheless|nonetheless|still)\b", re.IGNORECASE)


def has_affirmative_issue_prose(output: str) -> bool:
    for sentence in iter_review_prose_sentences(output):
        if not sentence:
            continue
        normalized_sentence = sentence.lower()
        if STRUCTURED_EMPTY_FINDINGS_RE.search(sentence):
            # Codex-style structured output often includes a literal empty findings
            # array alongside a clear explanation. Do not treat that field name as
            # affirmative issue prose.
            continue
        if not AFFIRMATIVE_ISSUE_WORD_RE.search(sentence):
            continue
        if has_affirmative_contrastive_issue_clause(sentence):
            return True
        if has_negated_clear_review_statement(normalized_sentence):
            continue
        if NEGATED_ISSUE_PROSE_RE.search(sentence):
            continue
        return True
    return False


def has_affirmative_contrastive_issue_clause(sentence: str) -> bool:
    """Return True when a contrastive clause still reports an issue.

    A sentence can negate issues in one clause and then introduce a real
    finding after a contrastive marker such as "but" or "however". The
    negation should not suppress the later clause.
    """

    for match in CONTRASTIVE_CLAUSE_RE.finditer(sentence):
        suffix = sentence[match.end() :]
        if not suffix:
            continue
        if not AFFIRMATIVE_ISSUE_WORD_RE.search(suffix):
            continue
        if NEGATED_ISSUE_PROSE_RE.search(suffix):
            continue
        return True
    return False


def iter_review_prose_sentences(output: str):
    """Yield prose fragments, treating line breaks as hard boundaries.

    Review summaries are often wrapped onto new lines without terminal
    punctuation, so line boundaries must split before sentence heuristics are
    applied. That keeps a clear statement on one line from suppressing an issue
    reported on the next line.
    """

    for paragraph in re.split(r"\n+", output.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            sentence = sentence.strip()
            if sentence:
                yield sentence


CLEAR_PHRASES = (
    # Keep only negated forms here. Broad phrases like "warrant an inline finding"
    # can appear in positive review prose and must not force a clear status.
    "did not find any discrete, actionable bugs",
    "did not find any discrete, actionable correctness issues",
    "did not find a discrete introduced bug",
    "did not find any discrete introduced bug",
    "did not find any actionable bugs",
    "did not identify a discrete introduced correctness, security, or maintainability issue that should block the patch",
    "did not identify any discrete introduced bugs that should block the patch",
    "did not identify any discrete introduced bugs that would block the patch",
    "did not identify any actionable correctness, security, or maintainability issues",
    "did not identify any introduced correctness, security, or maintainability issues",
    "did not identify any introduced correctness, security, or maintainability issues that warrant an inline finding",
    "without revealing any discrete correctness issue",
    "no discrete, actionable bugs",
    "no actionable bugs",
    "without any clear regressions or actionable bugs",
    "without any clear regressions or actionable",
)


def review_status_diagnostics(output: str) -> dict[str, object]:
    """Return compact, targeted diagnostics for review-status classification."""
    actionable_output = actionable_review_output(output)
    stderr_present = "\n[stderr]\n" in output
    explicit_status = STATUS_RE.search(actionable_output)
    finding_lines = CODEX_FINDING_RE.findall(actionable_output)
    normalized = actionable_output.lower()
    clear_phrase_present = (
        any(phrase in normalized for phrase in CLEAR_PHRASES)
        or has_negated_clear_review_statement(normalized)
    )
    return {
        "status": detect_review_status(output),
        "actionable_chars": len(actionable_output),
        "stderr_present": stderr_present,
        "explicit_status": explicit_status.group(1).lower() if explicit_status else None,
        "finding_line_count": len(finding_lines),
        "clear_phrase_present": clear_phrase_present,
    }


def extract_finding_summaries(output: str, limit: int = 5) -> list[str]:
    summaries: list[str] = []
    for line in actionable_review_output(output).splitlines():
        match = CODEX_FINDING_LINE_RE.match(line)
        if not match:
            continue
        summaries.append(match.group(1).strip())
        if len(summaries) >= limit:
            break
    return summaries


def extract_finding_blocks(output: str, limit: int = 5, detail_lines: int = 2) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    current_details = 0

    for raw_line in actionable_review_output(output).splitlines():
        match = CODEX_FINDING_LINE_RE.match(raw_line)
        if match:
            if current:
                blocks.append(current)
                if len(blocks) >= limit:
                    return blocks
            current = [match.group(1).strip()]
            current_details = 0
            continue

        if current is None or current_details >= detail_lines:
            continue

        stripped = raw_line.strip()
        if not stripped:
            continue
        current.append(stripped)
        current_details += 1

    if current and len(blocks) < limit:
        blocks.append(current)
    return blocks


def extract_review_summary(output: str) -> str:
    """Return the review's leading prose summary, excluding finding bullets."""
    text = actionable_review_output(output).strip()
    if not text:
        return ""
    text = REVIEW_COMMENTS_HEADING_RE.split(text, maxsplit=1)[0].strip()
    paragraphs = [
        " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        for paragraph in re.split(r"\n\s*\n", text)
    ]
    for paragraph in paragraphs:
        if paragraph and not CODEX_FINDING_LINE_RE.match(paragraph):
            return paragraph
    return ""


def log_review_findings(config: LoopConfig, label: str, output: str) -> bool:
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
        progress_event(config, "review", label, f"findings-summary ({len(blocks)})")
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


def strip_finding_priority(finding: str) -> tuple[str, str]:
    match = re.match(r"^(\[P[0-3]\])\s+(.+)$", finding)
    if not match:
        return "", finding
    return match.group(1), match.group(2)


def build_review_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.review_harness,
            role="review",
            executable=config.codex_bin,
            base=config.base,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
        )
    )


def build_remediation_command(config: LoopConfig, output_last_message: Path | None = None) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.remediation_harness,
            role="remediation",
            executable=config.codex_bin,
            model=config.remediation_model or config.model,
            reasoning_effort=config.remediation_reasoning_effort or config.reasoning_effort,
            sandbox=config.exec_sandbox,
            color=config.exec_color,
            full_auto=config.full_auto,
            json_output=config.exec_json,
            output_last_message=config.output_last_message,
            output_last_message_path=output_last_message,
        )
    )


def build_triage_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.triage_harness,
            role="triage",
            executable=config.codex_bin,
            model=config.triage_model,
            reasoning_effort=config.triage_reasoning_effort,
            sandbox="read-only",
            color=config.exec_color,
            full_auto=False,
        )
    )


def build_commit_message_command(config: LoopConfig) -> list[str]:
    return harnesses.build_phase_command(
        harnesses.PhaseCommandRequest(
            harness=config.commit_message_harness,
            role="commit-message",
            executable=config.codex_bin,
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


def write_artifact(path: Path, content: str) -> None:
    artifacts.write_text_artifact(path, content)


def run_codex_review(
    config: LoopConfig,
    runner: Runner,
    artifact_label: str,
    display_label: str | None = None,
) -> tuple[str, CommandResult]:
    display_label = display_label or artifact_label
    command = build_review_command(config)
    set_phase_terminal_title(config, "review", display_label)
    progress_event(config, "review", display_label, "start", shlex.join(command))
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN\nREVIEW_STATUS: findings\n")
    else:
        artifact_path = config.artifact_dir / f"{artifact_label}.txt"
        if preflight_error := review_base_preflight_error(config):
            write_artifact(artifact_path, preflight_error)
            progress_event(config, "review", display_label, "failed", "invalid base")
            raise RuntimeError(f"codex review failed for {artifact_label}; see {artifact_path}")
        result = runner(command, config.cwd, None, phase_timeout_seconds(config, config.review_timeout_seconds))
    combined = _combined_output(result)
    artifact_path = config.artifact_dir / f"{artifact_label}.txt"
    write_artifact(artifact_path, combined)
    if review_failed_to_run(result):
        progress_event(config, "review", display_label, "failed", f"exit {result.returncode}")
        raise RuntimeError(f"codex review failed for {artifact_label}; see {artifact_path}")
    status = detect_review_status(combined)
    if config.debug_status_detection:
        diagnostics = review_status_diagnostics(combined)
        write_artifact(
            config.artifact_dir / f"{artifact_label}-status.json",
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        )
        progress_event(
            config,
            "review",
            display_label,
            "status-debug",
            (
                f"status={diagnostics['status']} "
                f"findings={diagnostics['finding_line_count']} "
                f"clear_phrase={diagnostics['clear_phrase_present']} "
                f"stderr={diagnostics['stderr_present']}"
            ),
        )
    if status != "findings" or not log_review_findings(config, display_label, combined):
        progress_event(config, "review", display_label, status)
    return status, result


def review_base_preflight_error(config: LoopConfig) -> str | None:
    if config.dry_run or lexical_git_repo_root(config.cwd) is None:
        return None

    inside = run_git_preflight(config.cwd, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    base = config.base
    base_result = run_git_preflight(config.cwd, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    if base_result.returncode != 0:
        return (
            f"Review base preflight failed: base {base!r} is not a local commit.\n"
            f"Command: git rev-parse --verify {base}^{{commit}}\n"
            f"{_combined_output(base_result)}"
        )

    merge_base = run_git_preflight(config.cwd, ["merge-base", "HEAD", base])
    if merge_base.returncode == 0:
        return None

    head = run_git_preflight(config.cwd, ["rev-parse", "HEAD"]).stdout.strip() or "HEAD"
    base_sha = base_result.stdout.strip() or base
    hint = review_base_hint(config, base)
    return (
        f"Review base preflight failed: HEAD and base {base!r} do not share a merge base.\n"
        f"HEAD: {head}\n"
        f"{base}: {base_sha}\n"
        f"Command: git merge-base HEAD {base}\n"
        f"{_combined_output(merge_base)}"
        f"{hint}"
    )


def review_base_hint(config: LoopConfig, base: str) -> str:
    if "/" in base:
        return "Use a base branch that shares history with HEAD, or realign the local branch.\n"
    remote_base = f"origin/{base}"
    remote_base_result = run_git_preflight(
        config.cwd,
        ["rev-parse", "--verify", f"{remote_base}^{{commit}}"],
    )
    if remote_base_result.returncode == 0:
        remote_merge_base = run_git_preflight(config.cwd, ["merge-base", "HEAD", remote_base])
        if remote_merge_base.returncode == 0:
            return (
                f"Hint: {remote_base!r} does share history with HEAD. "
                f"Retry with --base {remote_base}, or update local {base!r} to match the PR base.\n"
            )
    return "Use a base branch that shares history with HEAD, or realign the local branch.\n"


def run_git_preflight(cwd: Path, args: Sequence[str]) -> CommandResult:
    command = ["git", *args]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command,
            -1,
            stdout=_timeout_stream_text(exc.output),
            stderr=_timeout_stream_text(exc.stderr),
        )
    return CommandResult(
        command,
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def review_failed_to_run(result: CommandResult) -> bool:
    """Distinguish review invocation failures from review findings."""
    if result.returncode == 0:
        return False
    if result.returncode < 0:
        return True
    if result.returncode >= 2:
        return True

    stderr = result.stderr.lower()
    fatal_markers = (
        "error:",
        "fatal error",
        "failed to create session",
        "thread/start failed",
        "for more information, try '--help'",
    )
    return any(marker in stderr for marker in fatal_markers)


def run_remediation(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    review_output: str,
) -> CommandResult:
    last_message_path = (
        config.artifact_dir / f"remediation-{iteration}-last-message.txt"
        if config.output_last_message
        else None
    )
    command = build_remediation_command(config, last_message_path)
    prompt = f"{DEFAULT_REMEDIATION_PROMPT}\n{trim_for_prompt(review_output, config.max_remediation_input_chars)}"
    set_phase_terminal_title(config, "remediate", str(iteration))
    progress_event(config, "remediate", str(iteration), "start", shlex.join(command))
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN remediation skipped\n")
    else:
        result = runner(command, config.cwd, prompt, phase_timeout_seconds(config, config.remediation_timeout_seconds))
    write_artifact(config.artifact_dir / f"remediation-{iteration}.txt", _combined_output(result))
    if result.returncode != 0:
        progress_event(config, "remediate", str(iteration), "failed", f"exit {result.returncode}")
        raise RuntimeError(
            f"codex exec remediation failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'remediation-{iteration}.txt'}"
        )
    progress_event(config, "remediate", str(iteration), "done")
    return result


def run_triage(
    config: LoopConfig,
    runner: Runner,
    iteration: int,
    run_id: str,
    source_review_artifact: str,
    review_output: str,
) -> tuple[str, int, bool]:
    command = build_triage_command(config)
    prompt_root = config.triage_prompt or triage.load_prompt()
    prompt = f"{prompt_root}\n{trim_for_prompt(review_output, config.max_remediation_input_chars)}"
    progress_event(config, "triage", str(iteration), "start", shlex.join(command))
    if config.dry_run:
        result = CommandResult(command, 0, stdout="DRY_RUN triage skipped\n")
    else:
        result = runner(command, config.cwd, prompt, phase_timeout_seconds(config, config.triage_timeout_seconds))
    write_artifact(config.artifact_dir / f"triage-{iteration}.txt", _combined_output(result))
    if result.returncode != 0:
        progress_event(config, "triage", str(iteration), "failed", f"exit {result.returncode}")
        raise RuntimeError(
            f"codex exec triage failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'triage-{iteration}.txt'}"
        )
    progress_event(config, "triage", str(iteration), "done")
    triage_output = actionable_review_output(_combined_output(result))
    if triage.looks_structured_output(triage_output):
        try:
            payload = triage.parse_triage_payload(
                triage_output,
                run_id=run_id,
                source_review_artifact=source_review_artifact,
            )
        except triage.TriageValidationError as exc:
            issue = triage.invalid_triage_issue(exc, iteration=iteration)
            artifacts.write_json_artifact(
                config.artifact_dir,
                f"diagnostics-{iteration}.json",
                triage.diagnostics_payload(issue),
            )
            progress_event(config, "triage", str(iteration), "invalid", str(exc))
            if config.triage_on_invalid == "stop":
                raise RuntimeError(f"invalid structured triage output for iteration {iteration}: {exc}") from exc
            return review_output, 0, False
        suppressed_count = 0
        if config.suppressions_enabled:
            matches = suppressions.load_effective_suppressions(config.cwd)
            payload, suppressed_findings = suppressions.apply_to_triage_payload(payload, matches)
            suppressed_count = len(suppressed_findings)
            if suppressed_findings:
                progress_event(
                    config,
                    "triage",
                    str(iteration),
                    "suppressed",
                    f"{len(suppressed_findings)} finding(s)",
                )
        triage.write_triage_artifact(config.artifact_dir, iteration, payload)
        has_actionable_findings = bool(payload.get("confirmed_findings") or payload.get("needs_more_info"))
        if not has_actionable_findings:
            return "", suppressed_count, True
        return triage.format_structured_handoff(payload, review_output), suppressed_count, False
    return (
        "Triage handoff from the previous review:\n"
        f"{triage_output}\n\n"
        "Original review/check context:\n"
        f"{review_output}"
    ), 0, False


def run_checks(config: LoopConfig, runner: Runner, iteration: int) -> list[CommandResult]:
    results: list[CommandResult] = []
    for index, check in enumerate(config.check_commands, start=1):
        command = shlex.split(check)
        progress_event(config, "check", f"{iteration}.{index}", "start", check)
        adaptive_skip = adaptive_check_skip_reason(command, config.cwd)
        if adaptive_skip:
            result = CommandResult(
                command,
                0,
                stdout=f"SKIPPED adaptive check: {adaptive_skip}\n",
            )
        elif config.dry_run:
            result = CommandResult(command, 0, stdout=f"DRY_RUN check skipped: {check}\n")
        else:
            # Checks intentionally follow the global loop timeout, not the
            # remediation-specific timeout, so remediation tuning does not make
            # verification commands spuriously fail or run forever.
            result = runner(command, config.cwd, None, phase_timeout_seconds(config, config.timeout_seconds))
            result = normalize_adaptive_check_result(command, config.cwd, result)
        results.append(result)
        write_artifact(
            config.artifact_dir / f"check-{iteration}-{index}.txt",
            _combined_output(result),
        )
        if result.returncode == 0 and result.stdout.startswith("SKIPPED adaptive check:"):
            progress_event(config, "check", f"{iteration}.{index}", "skipped", result.stdout.strip())
        elif result.returncode == 0:
            progress_event(config, "check", f"{iteration}.{index}", "passed")
        else:
            progress_event(config, "check", f"{iteration}.{index}", "failed", f"exit {result.returncode}")
    return results


def adaptive_check_skip_reason(command: Sequence[str], cwd: Path) -> str | None:
    if (
        is_pytest_command(command)
        and has_non_python_project_surface(cwd)
        and not has_python_test_surface(cwd)
    ):
        return "pytest check ignored because this repository appears to be non-Python"
    return None


def normalize_adaptive_check_result(
    command: Sequence[str],
    cwd: Path,
    result: CommandResult,
) -> CommandResult:
    if (
        is_pytest_command(command)
        and result.returncode in {2, 4, 5}
        and has_non_python_project_surface(cwd)
        and not has_python_test_surface(cwd)
    ):
        return CommandResult(
            list(result.args),
            0,
            stdout=(
                "SKIPPED adaptive check: pytest exited "
                f"{result.returncode}, but this repository appears to be non-Python\n"
                + _combined_output(result)
            ),
        )
    return result


def is_pytest_command(command: Sequence[str]) -> bool:
    if not command:
        return False
    first = Path(command[0]).name
    if first in {"pytest", "py.test"}:
        return True
    if first.startswith("pytest"):
        return True
    return len(command) >= 3 and first.startswith("python") and command[1:3] == ["-m", "pytest"]


PYTHON_PROJECT_MARKERS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "requirements.txt",
    "requirements-dev.txt",
)
PYTHON_SCAN_SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "dist",
    "build",
    "node_modules",
    "tmp",
}
NON_PYTHON_PROJECT_MARKERS = (
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "bun.lockb",
    "deno.json",
    "deno.jsonc",
    "tsconfig.json",
)


def has_non_python_project_surface(cwd: Path) -> bool:
    root = cwd.resolve()
    return any((root / marker).exists() for marker in NON_PYTHON_PROJECT_MARKERS)


def has_python_test_surface(cwd: Path) -> bool:
    root = cwd.resolve()
    if any((root / marker).exists() for marker in PYTHON_PROJECT_MARKERS):
        return True
    tests_dir = root / "tests"
    return tests_dir.is_dir() and any(
        path.suffix == ".py" for path in iter_project_files(tests_dir)
    )


def iter_project_files(root: Path):
    if not root.exists():
        return
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in PYTHON_SCAN_SKIP_DIRS and not name.startswith(".")
        ]
        current_path = Path(current)
        for filename in filenames:
            yield current_path / filename


def git_add_command_for_commit(_config: LoopConfig) -> list[str]:
    return ["git", "add", "-A"]


def git_worktree_status_command_for_commit(_config: LoopConfig) -> list[str]:
    return ["git", "status", "--porcelain=v1", "--untracked-files=all"]


def git_repo_root(start: Path) -> Path:
    resolved_start = start.resolve()
    for candidate in (resolved_start, *resolved_start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"unable to determine git repository root from {start}")


def commit_artifact_relative_path(config: LoopConfig) -> Path | None:
    repo_root = git_repo_root(config.cwd)
    artifact_root = (
        config.artifact_dir
        if config.artifact_dir.is_absolute()
        else config.cwd / config.artifact_dir
    )
    resolved_root = artifact_root.resolve()
    try:
        artifact_rel = resolved_root.relative_to(repo_root)
    except ValueError:
        return None
    if artifact_rel == Path("."):
        raise RuntimeError(
            "refusing to auto-commit when --artifact-dir resolves to the repository root; "
            "choose a subdirectory for generated artifacts."
        )
    return artifact_rel


def git_reset_artifact_command_for_commit(config: LoopConfig) -> list[str] | None:
    artifact_rel = commit_artifact_relative_path(config)
    if artifact_rel is None:
        return None
    repo_root = git_repo_root(config.cwd)
    # Keep generated loop artifacts out of the staged commit. Resolve artifact
    # paths from the git root so subdirectory invocations can still reset files
    # that live elsewhere inside the same repository.
    return ["git", "-C", str(repo_root), "reset", "--", artifact_rel.as_posix()]


def commit_command_for_message(config: LoopConfig, message: str) -> list[str]:
    command = ["git", "commit"]
    if config.commit_on_hook_failure == "no-verify":
        command.append("--no-verify")
    command.extend(["-m", message])
    return command


def classify_commit_failure(result: CommandResult) -> str:
    output = _combined_output(result)
    return "hook_failed" if COMMIT_HOOK_FAILURE_RE.search(output) else "commit_failed"


def run_commit(config: LoopConfig, runner: Runner, iteration: int) -> str:
    progress_event(config, "commit", str(iteration), "start", "stage and commit verified remediation")
    if config.dry_run:
        write_artifact(config.artifact_dir / f"commit-{iteration}.txt", "DRY_RUN commit skipped\n")
        progress_event(config, "commit", str(iteration), "skipped", "dry-run")
        return "skipped"

    commit_artifact_relative_path(config)
    add_result = runner(
        git_add_command_for_commit(config),
        config.cwd,
        None,
        phase_timeout_seconds(config, config.timeout_seconds),
    )
    write_artifact(config.artifact_dir / f"commit-{iteration}-add.txt", _combined_output(add_result))
    if add_result.returncode != 0:
        progress_event(config, "commit", str(iteration), "failed", "git add failed")
        raise RuntimeError(
            f"git add failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'commit-{iteration}-add.txt'}"
        )

    reset_command = git_reset_artifact_command_for_commit(config)
    if reset_command is not None:
        reset_result = runner(
            reset_command,
            config.cwd,
            None,
            phase_timeout_seconds(config, config.timeout_seconds),
        )
        write_artifact(config.artifact_dir / f"commit-{iteration}-reset-artifacts.txt", _combined_output(reset_result))
        if reset_result.returncode != 0:
            progress_event(config, "commit", str(iteration), "failed", "git reset artifacts failed")
            raise RuntimeError(
                f"git reset artifacts failed for iteration {iteration}; "
                f"see {config.artifact_dir / f'commit-{iteration}-reset-artifacts.txt'}"
            )

    diff_quiet = runner(
        ["git", "diff", "--cached", "--quiet"],
        config.cwd,
        None,
        phase_timeout_seconds(config, config.timeout_seconds),
    )
    if diff_quiet.returncode == 0:
        write_artifact(config.artifact_dir / f"commit-{iteration}.txt", "No staged changes to commit.\n")
        progress_event(config, "commit", str(iteration), "skipped", "no staged changes")
        return "skipped_no_changes"
    if diff_quiet.returncode != 1:
        write_artifact(config.artifact_dir / f"commit-{iteration}.txt", _combined_output(diff_quiet))
        progress_event(config, "commit", str(iteration), "failed", "git diff --cached --quiet failed")
        raise RuntimeError(f"git staged-diff check failed for iteration {iteration}")

    message = commit_message_for_staged_changes(config, runner, iteration)
    commit_result = runner(
        commit_command_for_message(config, message),
        config.cwd,
        None,
        phase_timeout_seconds(config, config.timeout_seconds),
    )
    commit_artifact_path = config.artifact_dir / f"commit-{iteration}.txt"
    commit_output = _combined_output(commit_result)
    write_artifact(commit_artifact_path, commit_output)
    if commit_result.returncode != 0:
        kind = classify_commit_failure(commit_result)
        detail = "git commit hook failed" if kind == "hook_failed" else "git commit failed"
        progress_event(config, "commit", str(iteration), "failed", detail)
        raise CommitFailed(
            iteration=iteration,
            kind=kind,
            artifact_path=commit_artifact_path,
            output=commit_output,
        )
    write_artifact(config.artifact_dir / f"commit-{iteration}-message.txt", message + "\n")
    progress_event(config, "commit", str(iteration), "committed", message)
    return "committed"


def commit_message_for_staged_changes(config: LoopConfig, runner: Runner, iteration: int) -> str:
    fallback = deterministic_commit_message(iteration)
    stat = runner(["git", "diff", "--cached", "--stat"], config.cwd, None, phase_timeout_seconds(config, config.timeout_seconds))
    names = runner(["git", "diff", "--cached", "--name-only"], config.cwd, None, phase_timeout_seconds(config, config.timeout_seconds))
    context = "\n".join(
        part
        for part in (
            "Files:",
            names.stdout.strip(),
            "",
            "Stat:",
            stat.stdout.strip(),
        )
        if part is not None
    )
    if not config.commit_message_model:
        return fallback
    command = build_commit_message_command(config)
    prompt_root = config.commit_message_prompt or DEFAULT_COMMIT_MESSAGE_PROMPT
    prompt = f"{prompt_root}\n{trim_for_prompt(context, config.max_remediation_input_chars)}"
    result = runner(command, config.cwd, prompt, phase_timeout_seconds(config, config.timeout_seconds))
    write_artifact(config.artifact_dir / f"commit-{iteration}-message-draft.txt", _combined_output(result))
    if result.returncode != 0:
        return fallback
    return sanitize_commit_message(
        actionable_review_output(_combined_output(result)),
        fallback=fallback,
        enforce_revrem_conventional=not config.commit_message_prompt_overridden,
    )


def deterministic_commit_message(iteration: int) -> str:
    return f"chore: remediate review iteration {iteration} (RevRem)"


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


def _format_check_failures(check_results: list[CommandResult]) -> str:
    failures = [r for r in check_results if r.returncode != 0]
    if not failures:
        return ""
    parts = ["Check failures from the previous iteration:"]
    for r in failures:
        parts.append(f"\n$ {shlex.join(r.args)}\n{_combined_output(r)}")
    return "\n".join(parts)


def actionable_review_output(output: str) -> str:
    """Keep the review's actionable comments, not the verbose tool transcript."""
    review_text = output.split("\n[stderr]\n", 1)[0].strip()
    if not review_text:
        review_text = output.strip()
    return review_text


def trim_for_prompt(text: str, max_chars: int) -> str:
    if max_chars < 1:
        raise ValueError("max prompt characters must be positive")
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    marker = f"\n\n[... omitted {omitted} characters to stay under prompt limit ...]\n\n"
    if len(marker) >= max_chars:
        return marker[:max_chars]
    keep_total = max_chars - len(marker)
    keep_head = keep_total // 2
    keep_tail = keep_total - keep_head
    return (
        text[:keep_head]
        + marker
        + text[-keep_tail:]
    )


def excerpt_for_terminal(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    return trim_for_prompt(text, max_chars)


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
            if path.name.startswith("remediation-") and "last-message" not in path.name
        ],
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
            if path.name.endswith("-status.json") or path.name.startswith("diagnostics-")
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


def format_commit_hook_failure_for_remediation(exc: CommitFailed) -> str:
    return "\n".join(
        [
            "Commit hook failure from the previous RevRem iteration.",
            "",
            "Treat this as a verification failure. Remediate the underlying cause,",
            "preserve staged work, and do not bypass hooks unless the operator explicitly",
            "configured that policy.",
            "",
            f"Commit artifact: {exc.artifact_path}",
            "",
            "git commit output:",
            trim_for_prompt(exc.output, 20_000),
        ]
    ).strip()


def run_loop(config: LoopConfig, runner: Runner = default_runner) -> dict[str, object]:
    with (
        terminal_recovery_context(),
        terminal_title_context(config),
        progress_warning_context(),
        progress.rich_live_progress(config.progress and config.progress_style == "rich"),
    ):
        return _run_loop(config, runner)


def _run_loop(config: LoopConfig, runner: Runner = default_runner) -> dict[str, object]:
    if config.max_iterations < 1:
        raise ValueError("--max-iterations must be at least 1")

    if config.commit_after_remediation and not config.dry_run:
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

    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_artifact_ignore(config)
    iterations: list[dict[str, object]] = []
    run_id = uuid.uuid4().hex
    summary: dict[str, object] = {
        "base": config.base,
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "profile": config.profile_name,
        "max_iterations": config.max_iterations,
        "artifact_dir": str(config.artifact_dir),
        "iterations": iterations,
        "commit_on_hook_failure": config.commit_on_hook_failure,
        "commit_no_verify": config.commit_on_hook_failure == "no-verify",
        "final_status": "unknown",
        "initial_review_file": str(config.initial_review_file) if config.initial_review_file else None,
        "pending_check_failures": False,
        "stopped_reason": None,
    }

    pending_check_failures = ""
    initial_review_output = ""
    if config.initial_review_file:
        initial_review_output = actionable_review_output(
            config.initial_review_file.read_text(encoding="utf-8")
        )
        write_artifact(config.artifact_dir / "review-initial.txt", initial_review_output + "\n")
        progress_event(config, "review", "initial", "loaded", str(config.initial_review_file))
        log_review_findings(config, "initial", initial_review_output)

    for iteration in range(1, config.max_iterations + 1):
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
        else:
            try:
                status, review = run_codex_review(
                    config,
                    runner,
                    f"review-{iteration}",
                    display_label=str(iteration),
                )
            except RuntimeError as exc:
                iterations.append({"iteration": iteration, "review_failed": True})
                summary["final_status"] = "error"
                summary["stopped_reason"] = "review_failed"
                summary["error"] = str(exc)
                write_summary(config, summary)
                raise RunLoopFailed(summary, str(exc)) from exc
            last_review_output = actionable_review_output(_combined_output(review))
            iterations.append({"iteration": iteration, "review_status": status})

        if status == "clear" and not pending_check_failures:
            summary["final_status"] = "clear"
            summary["stopped_reason"] = "review_clear"
            summary["latest_review_excerpt"] = excerpt_for_terminal(
                last_review_output,
                config.terminal_excerpt_chars,
            )
            write_summary(config, summary)
            return summary

        remediation_input = last_review_output
        if pending_check_failures:
            remediation_input = pending_check_failures + "\n\n" + remediation_input
        try:
            if config.triage_enabled:
                # Resumed runs keep the loaded review in review-initial.txt, so triage must
                # point at that artifact instead of assuming review-1.txt.
                source_review_artifact = (
                    "review-initial.txt" if iteration == 1 and initial_review_output else f"review-{iteration}.txt"
                )
                remediation_input, suppressed_count, triage_no_actionable = run_triage(
                    config,
                    runner,
                    iteration,
                    run_id,
                    source_review_artifact,
                    remediation_input,
                )
                if suppressed_count:
                    iterations[-1]["suppressed_findings_count"] = suppressed_count
                if triage_no_actionable:
                    if suppressed_count:
                        iterations[-1]["suppressed_findings"] = True
                        summary["suppressed_findings_count"] = suppressed_count
                    if not pending_check_failures:
                        iterations[-1]["check_failures"] = 0
                        summary["final_status"] = "clear"
                        summary["stopped_reason"] = (
                            "all_findings_suppressed" if suppressed_count else "triage_rejected_all_findings"
                        )
                        summary["latest_review_excerpt"] = excerpt_for_terminal(
                            last_review_output,
                            config.terminal_excerpt_chars,
                        )
                        write_summary(config, summary)
                        return summary
                    remediation_input = pending_check_failures
        except Exception as exc:
            summary["final_status"] = "error"
            summary["stopped_reason"] = "triage_failed"
            summary["error"] = str(exc)
            iterations[-1]["triage_failed"] = True
            write_summary(config, summary)
            raise RunLoopFailed(
                summary,
                f"codex exec triage failed for iteration {iteration}; "
                f"see {config.artifact_dir / f'triage-{iteration}.txt'}",
            ) from exc

        try:
            run_remediation(config, runner, iteration, remediation_input)
        except Exception as exc:
            summary["final_status"] = "error"
            summary["stopped_reason"] = "remediation_failed"
            summary["error"] = str(exc)
            iterations[-1]["remediation_failed"] = True
            write_summary(config, summary)
            raise RunLoopFailed(
                summary,
                f"codex exec remediation failed for iteration {iteration}; "
                f"see {config.artifact_dir / f'remediation-{iteration}.txt'}",
            ) from exc

        check_results = run_checks(config, runner, iteration)
        pending_check_failures = _format_check_failures(check_results)
        iterations[-1]["check_failures"] = sum(1 for result in check_results if result.returncode != 0)
        if config.commit_after_remediation and not pending_check_failures:
            try:
                iterations[-1]["commit_status"] = run_commit(config, runner, iteration)
            except CommitFailed as exc:
                iterations[-1]["commit_status"] = exc.kind
                iterations[-1]["commit_failed"] = True
                iterations[-1]["commit_artifact"] = str(exc.artifact_path)
                is_retryable_hook_failure = (
                    exc.kind == "hook_failed"
                    and config.commit_on_hook_failure == "remediate"
                    and iteration < config.max_iterations
                )
                if is_retryable_hook_failure:
                    pending_check_failures = format_commit_hook_failure_for_remediation(exc)
                    summary["pending_check_failures"] = True
                    progress_event(
                        config,
                        "commit",
                        str(iteration),
                        "retry",
                        "hook output will feed next remediation",
                    )
                    continue
                stopped_reason = (
                    "commit_hook_failed" if exc.kind == "hook_failed" else "commit_failed"
                )
                summary["final_status"] = "error"
                summary["stopped_reason"] = stopped_reason
                summary["error"] = str(exc)
                if exc.kind == "hook_failed":
                    summary["staged_changes_left"] = True
                    summary["pending_check_failures"] = True
                write_summary(config, summary)
                raise RunLoopFailed(summary, str(exc)) from exc
            except Exception as exc:
                summary["final_status"] = "error"
                summary["stopped_reason"] = "commit_failed"
                summary["error"] = str(exc)
                iterations[-1]["commit_failed"] = True
                write_summary(config, summary)
                raise RunLoopFailed(summary, f"git commit failed for iteration {iteration}") from exc
            if iterations[-1]["commit_status"] == "skipped_no_changes":
                summary["final_status"] = status
                summary["stopped_reason"] = "no_changes_after_remediation"
                summary["latest_review_excerpt"] = excerpt_for_terminal(
                    last_review_output,
                    config.terminal_excerpt_chars,
                )
                write_summary(config, summary)
                return summary

    if config.final_review:
        try:
            status, final_review = run_codex_review(
                config,
                runner,
                "review-final",
                display_label="final",
            )
        except RuntimeError as exc:
            iterations.append({"iteration": "final", "review_failed": True})
            summary["final_status"] = "error"
            summary["stopped_reason"] = "review_failed"
            summary["error"] = str(exc)
            write_summary(config, summary)
            raise RunLoopFailed(summary, str(exc)) from exc
        final_review_output = actionable_review_output(_combined_output(final_review))
        summary["latest_review_excerpt"] = excerpt_for_terminal(
            final_review_output,
            config.terminal_excerpt_chars,
        )
        if pending_check_failures:
            summary["final_status"] = "findings"
            summary["pending_check_failures"] = True
            summary["stopped_reason"] = "max_iterations_reached_with_check_failures"
        else:
            summary["final_status"] = status
            summary["stopped_reason"] = "review_clear" if status == "clear" else "max_iterations_reached"
            if status == "unknown":
                iterations.append(
                    {
                        "iteration": "final",
                        "review_status": status,
                    }
                )
    else:
        # Status after the last remediation is not known without a review.
        summary["final_status"] = "unknown"
        summary["pending_check_failures"] = bool(pending_check_failures)
        summary["stopped_reason"] = "max_iterations_reached"

    write_summary(config, summary)
    return summary


def write_summary(config: LoopConfig, summary: dict[str, object]) -> None:
    update_unexpected_behaviors(config, summary)
    add_summary_contract_fields(config, summary)
    add_artifact_paths(summary, config)
    artifacts.write_json_artifact(config.artifact_dir, "summary.json", summary)


def add_summary_contract_fields(config: LoopConfig, summary: dict[str, object]) -> None:
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
            "iteration_count": len(iterations) if isinstance(iterations, list) else 0,
        },
    )
    summary.setdefault("finished_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
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


def format_terminal_summary(summary: dict[str, object]) -> str:
    artifact_dir = str(summary.get("artifact_dir") or "")
    status = str(summary.get("final_status") or "unknown")
    reason = str(summary.get("stopped_reason") or "unknown")
    lines = [
        f"Review-remediation loop: {status} ({reason})",
        f"Artifacts: {artifact_dir}",
    ]
    history_path = summary.get("history_path")
    if history_path:
        lines.append(f"Run history: {history_path}")

    iterations = summary.get("iterations")
    if isinstance(iterations, list) and iterations:
        lines.append("Iterations:")
        for item in iterations:
            if not isinstance(item, dict):
                continue
            iteration = item.get("iteration")
            review_status = item.get("review_status", "unknown")
            check_failures = item.get("check_failures")
            check_text = "checks not run" if check_failures is None else f"check failures: {check_failures}"
            failed = " remediation failed" if item.get("remediation_failed") else ""
            commit_status = item.get("commit_status")
            commit_text = f", commit={commit_status}" if commit_status else ""
            commit_failed = " commit failed" if item.get("commit_failed") else ""
            lines.append(
                f"  {iteration}: review={review_status}, {check_text}{failed}"
                f"{commit_text}{commit_failed}"
            )

    artifact_paths = summary.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        reviews = artifact_paths.get("reviews")
        last_messages = artifact_paths.get("last_messages")
        checks = artifact_paths.get("checks")
        if isinstance(reviews, list) and reviews:
            lines.append(f"Latest review: {reviews[-1]}")
            if status == "findings":
                lines.append(f"Continue from latest review: --initial-review-file {reviews[-1]}")
        if isinstance(last_messages, list) and last_messages:
            lines.append(f"Latest remediation summary: {last_messages[-1]}")
        if isinstance(checks, list) and checks:
            lines.append(f"Latest check outputs: {', '.join(str(path) for path in checks[-2:])}")
        commits = artifact_paths.get("commits")
        if isinstance(commits, list) and commits:
            commit_outputs = [
                str(path)
                for path in commits
                if re.search(r"(?:^|/)commit-\d+\.txt$", str(path))
            ]
            lines.append(f"Latest commit artifact: {(commit_outputs or commits)[-1]}")
        summary_path = artifact_paths.get("summary")
        if summary_path:
            lines.append(f"JSON summary: {summary_path}")

    excerpt = str(summary.get("latest_review_excerpt") or "").strip()
    if excerpt and status != "clear":
        lines.append("")
        lines.append("Latest actionable review output:")
        lines.append(excerpt)

    if summary.get("error"):
        lines.append("")
        lines.append(f"Error: {summary['error']}")

    unexpected = summary.get("unexpected_behaviors")
    if isinstance(unexpected, list) and unexpected:
        lines.append("")
        lines.append("WARNING: unexpected loop behavior detected.")
        lines.append("Review status was classified as unknown during this run.")
        bug_report_path = summary.get("bug_report_path")
        if bug_report_path:
            lines.append(f"Bug report details: {bug_report_path}")

    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem",
        description="Run a bounded Codex review/remediation loop against a base branch.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--profile", default=None, help="Named profile from RevRem TOML config.")
    parser.add_argument("--base", default=None, help="Base branch passed to codex review.")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum remediation passes before stopping. Default: 2.",
    )
    parser.add_argument("--codex-bin", default=None, help="Codex executable path/name.")
    parser.add_argument("--model", default=None, help="Optional model passed to both Codex review and remediation.")
    parser.add_argument("--review-model", default=None, help="Optional model override for codex review only.")
    parser.add_argument(
        "--remediation-model",
        default=None,
        help="Optional model override for codex exec remediation only.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=None,
        help=(
            "Optional Codex model_reasoning_effort override for review and remediation; "
            "profiles may still set phase-specific values."
        ),
    )
    parser.add_argument(
        "--review-reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=None,
        help="Optional Codex model_reasoning_effort override for review only.",
    )
    parser.add_argument(
        "--triage-reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=None,
        help="Optional Codex model_reasoning_effort override for triage only.",
    )
    parser.add_argument(
        "--remediation-reasoning-effort",
        "--remediate-reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=None,
        help="Optional Codex model_reasoning_effort override for remediation only.",
    )
    parser.add_argument(
        "--commit-reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=None,
        help="Optional Codex model_reasoning_effort override for commit-message drafting only.",
    )
    parser.add_argument(
        "--exec-sandbox",
        default=None,
        choices=("read-only", "workspace-write", "danger-full-access"),
        help="Sandbox mode for codex exec remediation passes.",
    )
    parser.add_argument(
        "--exec-color",
        default=None,
        choices=("always", "never", "auto"),
        help="Color mode for codex exec remediation output. Default: never.",
    )
    exec_json_group = parser.add_mutually_exclusive_group()
    exec_json_group.add_argument(
        "--exec-json",
        dest="exec_json",
        action="store_true",
        default=None,
        help="Pass --json to codex exec and capture JSONL event output.",
    )
    exec_json_group.add_argument(
        "--no-exec-json",
        dest="exec_json",
        action="store_false",
        help="Do not pass --json to codex exec even when a profile enables it.",
    )
    output_last_message_group = parser.add_mutually_exclusive_group()
    output_last_message_group.add_argument(
        "--output-last-message",
        dest="output_last_message",
        action="store_true",
        default=None,
        help="Pass --output-last-message to codex exec remediation passes.",
    )
    output_last_message_group.add_argument(
        "--no-output-last-message",
        dest="output_last_message",
        action="store_false",
        default=None,
        help="Do not pass --output-last-message to codex exec remediation passes.",
    )
    full_auto_group = parser.add_mutually_exclusive_group()
    full_auto_group.add_argument(
        "--full-auto",
        dest="full_auto",
        action="store_true",
        default=None,
        help="Pass --full-auto to codex exec.",
    )
    full_auto_group.add_argument(
        "--no-full-auto",
        dest="full_auto",
        action="store_false",
        default=None,
        help="Do not pass --full-auto to codex exec.",
    )
    parser.add_argument(
        "--check",
        action="append",
        default=None,
        help="Verification command to run after each remediation pass. Repeatable.",
    )
    commit_group = parser.add_mutually_exclusive_group()
    commit_group.add_argument(
        "--commit-after-remediation",
        dest="commit_after_remediation",
        action="store_true",
        default=None,
        help=(
            "Stage and commit after each remediation pass whose verification checks pass. "
            "Requires a clean worktree before the loop starts and rejects artifact "
            "directories that resolve to the repository root; artifact paths are reset "
            "from the git root so subdirectory runs can still exclude generated files."
        ),
    )
    commit_group.add_argument(
        "--no-commit-after-remediation",
        dest="commit_after_remediation",
        action="store_false",
        help="Disable automatic commits even when the selected profile enables them.",
    )
    parser.add_argument(
        "--commit-message-model",
        default=None,
        help=(
            "Optional model for drafting commit subjects. Defaults to profile commit.message_model, "
            "then remediation/review model fallbacks."
        ),
    )
    parser.add_argument(
        "--commit-message-prompt",
        default=None,
        help=(
            "Override the commit-message drafting prompt. When set, RevRem does not enforce "
            "its default Conventional Commit + '(RevRem)' subject policy."
        ),
    )
    parser.add_argument(
        "--commit-on-hook-failure",
        choices=COMMIT_ON_HOOK_FAILURE_CHOICES,
        default=None,
        help=(
            "Policy when git commit appears to fail inside hooks: remediate feeds hook output "
            "into the next bounded pass, stop fails gracefully, no-verify commits with "
            "--no-verify. Default: profile commit.on_hook_failure or remediate."
        ),
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Directory for review/remediation/check transcripts.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the loop shape without running Codex.")
    final_review_group = parser.add_mutually_exclusive_group()
    final_review_group.add_argument(
        "--final-review",
        dest="final_review",
        action="store_true",
        default=None,
        help="Run the final review after the last remediation pass.",
    )
    final_review_group.add_argument(
        "--skip-final-review",
        dest="final_review",
        action="store_false",
        default=None,
        help="Do not run the final review after the last remediation pass.",
    )
    parser.add_argument(
        "--max-remediation-input-chars",
        type=int,
        default=None,
        help="Maximum review/check text characters passed into each remediation prompt.",
    )
    parser.add_argument(
        "--terminal-excerpt-chars",
        type=int,
        default=None,
        help="Maximum latest-review characters shown in terminal text summaries.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help=(
            "Maximum seconds for each review, remediation, or check command. "
            "Use 0 to disable subprocess timeouts. Default: 300."
        ),
    )
    parser.add_argument(
        "--summary-format",
        choices=("text", "json", "both"),
        default=None,
        help="Summary format printed to stdout. Full JSON is always written to summary.json.",
    )
    debug_status_group = parser.add_mutually_exclusive_group()
    debug_status_group.add_argument(
        "--debug-status-detection",
        dest="debug_status_detection",
        action="store_true",
        default=None,
        help="Write per-review status-classification diagnostics next to review artifacts.",
    )
    debug_status_group.add_argument(
        "--no-debug-status-detection",
        dest="debug_status_detection",
        action="store_false",
        help="Disable status-classification diagnostics even when a profile enables them.",
    )
    quiet_progress_group = parser.add_mutually_exclusive_group()
    quiet_progress_group.add_argument(
        "--quiet-progress",
        dest="quiet_progress",
        action="store_true",
        default=None,
        help="Suppress timestamped progress logs on stderr.",
    )
    quiet_progress_group.add_argument(
        "--no-quiet-progress",
        dest="quiet_progress",
        action="store_false",
        help="Show progress logs even when a profile suppresses them.",
    )
    parser.add_argument(
        "--progress-style",
        choices=PROGRESS_STYLE_CHOICES,
        default=None,
        help="Progress log style. Compact is easiest to scan in logs; rich is used only when Rich is installed.",
    )
    terminal_title_group = parser.add_mutually_exclusive_group()
    terminal_title_group.add_argument(
        "--terminal-title",
        dest="terminal_title",
        action="store_true",
        default=None,
        help=(
            "Update the terminal window/tab title with the active review or remediation phase. "
            "Restores the previous title on exit in terminals with xterm-style title-stack support."
        ),
    )
    terminal_title_group.add_argument(
        "--no-terminal-title",
        dest="terminal_title",
        action="store_false",
        help="Do not update the terminal title even when a profile enables it.",
    )
    parser.add_argument(
        "--initial-review-file",
        type=str,
        default=None,
        help=(
            "Start by remediating a previous review artifact. Use 'latest' for the newest "
            "usable non-clear review-final.txt; if none exists, start with a fresh review."
        ),
    )
    parser.add_argument(
        "--no-run-history",
        action="store_true",
        help="Do not append metadata for this non-dry-run invocation to the local RevRem history.",
    )
    parser.add_argument(
        "--save-profile",
        metavar="NAME",
        help=(
            "Save the effective CLI/profile configuration as NAME in the project-local "
            ".revrem.toml and exit without running the loop."
        ),
    )
    parser.add_argument(
        "--save-profile-force",
        action="store_true",
        help="Replace an existing project-local profile when used with --save-profile.",
    )
    return parser.parse_args(argv)


def parse_config_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem config",
        description="Manage RevRem TOML profiles.",
    )
    parser.add_argument("--format", choices=("text", "json"), default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available profiles.")
    list_parser.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    show = subparsers.add_parser("show", help="Show a resolved profile.")
    show.add_argument("name")
    show.add_argument("--format", choices=("toml", "json"), default=argparse.SUPPRESS)

    new = subparsers.add_parser(
        "new",
        help="Create a user profile, prompting for common fields in interactive terminals.",
    )
    new.add_argument("name")
    new.add_argument("--description", default="")
    new_interactive = new.add_mutually_exclusive_group()
    new_interactive.add_argument(
        "--interactive",
        dest="interactive",
        action="store_true",
        default=None,
        help="Prompt for common profile fields before writing the profile.",
    )
    new_interactive.add_argument(
        "--no-interactive",
        dest="interactive",
        action="store_false",
        help="Create the minimal profile without prompting.",
    )
    new.add_argument("--force", action="store_true")

    edit = subparsers.add_parser("edit", help="Open the owning config file in $EDITOR.")
    edit.add_argument("name")

    clone = subparsers.add_parser("clone", help="Clone a resolved profile into the user config.")
    clone.add_argument("source")
    clone.add_argument("target")
    clone.add_argument("--force", action="store_true")

    delete = subparsers.add_parser("delete", help="Delete a user profile.")
    delete.add_argument("name")
    delete.add_argument("--yes", action="store_true")

    export = subparsers.add_parser("export", help="Export a resolved profile as TOML.")
    export.add_argument("name")

    import_parser = subparsers.add_parser(
        "import",
        help="Import profiles from a TOML file.",
        description=(
            "Import profiles from a TOML file. If the source file contains [defaults], "
            "RevRem folds those defaults into each imported profile before writing the "
            "destination config, preserving the source profile behavior."
        ),
    )
    import_parser.add_argument("path")
    import_parser.add_argument("--force", action="store_true")

    doctor = subparsers.add_parser("doctor", help="Show config paths and merge diagnostics.")
    doctor.add_argument("--profile", default=None)
    doctor.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    return parser.parse_args(argv)


def parse_history_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem history",
        description="Inspect local RevRem run history.",
    )
    parser.add_argument("--format", choices=("text", "json"), default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List recent runs.")
    list_parser.add_argument("--limit", type=int, default=10)
    list_parser.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    return parser.parse_args(argv)


def parse_doctor_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem doctor",
        description="Run local RevRem setup diagnostics without invoking a model.",
    )
    parser.add_argument("--format", choices=("text", "json"), default=None)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when warnings are present.")
    parser.add_argument("--profile", default=None, help="Resolve defaults from a named profile.")
    parser.add_argument("--base", default=None, help="Base ref to validate. Defaults to profile/main.")
    parser.add_argument("--codex-bin", default=None, help="Codex executable path/name to validate.")
    parser.add_argument("--artifact-dir", default=None, help="Artifact directory to validate.")
    parser.add_argument("--check", action="append", default=None, help="Check command to validate. Repeatable.")
    parser.add_argument(
        "--commit-after-remediation",
        action="store_true",
        help="Validate commit-mode preconditions such as a clean worktree and a non-root artifact directory.",
    )
    return parser.parse_args(argv)


def parse_bundle_bug_report_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem bundle-bug-report",
        description="Create a redacted, deterministic bug-report bundle from a RevRem run directory.",
    )
    parser.add_argument("run_dir")
    parser.add_argument("--output", default=None)
    parser.add_argument("--include-raw-transcripts", action="store_true")
    parser.add_argument("--no-redact", action="store_true")
    parser.add_argument("--i-understand-the-risks", action="store_true")
    return parser.parse_args(argv)


def _profile_config_owner_path(name: str, cwd: Path, home: Path | None = None) -> Path:
    project_path = profiles.project_config_path(cwd)
    project_file = profiles.load_profile_file(project_path)
    if name in project_file.profiles:
        return project_path

    user_path = profiles.user_config_path(home)
    user_file = profiles.load_profile_file(user_path)
    if name in user_file.profiles:
        return user_path

    raise FileNotFoundError(f"profile not found: {name}")


def _editor_command() -> list[str]:
    editor = os.environ.get("EDITOR", "").strip()
    if not editor:
        raise RuntimeError("EDITOR is not set; cannot open a config editor")
    command = shlex.split(editor)
    if not command:
        raise RuntimeError("EDITOR is empty; cannot open a config editor")
    return command


def edit_profile_config(name: str, *, cwd: Path, home: Path | None = None) -> Path:
    path = _profile_config_owner_path(name, cwd, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    command = _editor_command() + [str(path)]
    try:
        subprocess.run(command, cwd=path.parent, check=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"editor not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"editor exited with status {exc.returncode}") from exc
    return path


def should_prompt_for_new_profile(args: argparse.Namespace) -> bool:
    if args.interactive is not None:
        return bool(args.interactive)
    return sys.stdin.isatty() and sys.stdout.isatty() and not args.description


def new_profile_from_args(args: argparse.Namespace) -> profiles.Profile:
    if should_prompt_for_new_profile(args):
        return profiles.prompt_for_new_profile(args.name)
    return profiles.minimal_profile(args.name, description=args.description)


def default_artifact_dir() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".revrem") / "runs" / f"{timestamp}-{uuid.uuid4().hex}"


def ensure_default_artifact_ignore(config: LoopConfig) -> None:
    artifact_dir = config.artifact_dir if config.artifact_dir.is_absolute() else config.cwd / config.artifact_dir
    default_runs_dir = config.cwd / ".revrem" / "runs"
    try:
        artifact_dir.relative_to(default_runs_dir)
    except ValueError:
        return
    # Keep the ignore file scoped to the workspace path the operator invoked,
    # rather than resolving through symlinked ancestry and mutating an
    # unrelated checkout's metadata.
    repo_root = lexical_git_repo_root(config.cwd)
    if repo_root == Path(tempfile.gettempdir()).resolve():
        repo_root = None
    ignore_path = git_info_exclude_path(repo_root) if repo_root is not None else None
    if ignore_path is not None and repo_root is not None:
        ignore_entry = f"{default_runs_dir.relative_to(repo_root).as_posix()}/"
    else:
        ignore_entry = "runs/"
    ignore_path = ignore_path or (config.cwd / ".revrem" / ".gitignore")
    if ignore_path.exists():
        existing = ignore_path.read_text(encoding="utf-8")
        existing_entries = set(existing.splitlines())
        if ignore_entry in existing_entries:
            return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        ignore_path.write_text(f"{existing}{ignore_entry}\n", encoding="utf-8")
        return
    ignore_path.parent.mkdir(parents=True, exist_ok=True)
    ignore_path.write_text(f"{ignore_entry}\n", encoding="utf-8")


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


def lexical_git_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_timeout_seconds(value: float) -> float | None:
    if value < 0:
        raise ValueError("--timeout-seconds must be 0 or greater")
    if value == 0:
        return None
    return value


def resolve_profile_timeout_seconds(value: float | None) -> float | None:
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    return value


def profile_or_default(
    name: str | None,
    cwd: Path,
    *,
    require_implemented: bool = True,
) -> profiles.Profile:
    if name:
        return profiles.resolve_profile(name, cwd=cwd, require_implemented=require_implemented)
    return profiles.resolve_defaults(cwd=cwd, require_implemented=require_implemented)


def pick(cli_value, profile_value, fallback):
    if cli_value is not None:
        return cli_value
    if profile_value is not None:
        return profile_value
    return fallback


def build_loop_config(args: argparse.Namespace, cwd: Path) -> tuple[LoopConfig, str]:
    profile = profile_or_default(args.profile, cwd)
    if args.timeout_seconds is not None:
        timeout_seconds = resolve_timeout_seconds(args.timeout_seconds)
        review_timeout_seconds = timeout_seconds
        remediation_timeout_seconds = timeout_seconds
        triage_timeout_seconds = timeout_seconds if profile.triage.enabled else None
    else:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        review_timeout_seconds = resolve_profile_timeout_seconds(profile.review.timeout_seconds)
        remediation_timeout_seconds = resolve_profile_timeout_seconds(profile.remediation.timeout_seconds)
        triage_timeout_seconds = (
            resolve_profile_timeout_seconds(profile.triage.timeout_seconds)
            if profile.triage.enabled
            else None
        )
    commit_after_remediation = (
        args.commit_after_remediation
        if args.commit_after_remediation is not None
        else profile.commit.enabled
    )
    if commit_after_remediation and not args.dry_run:
        harnesses.require_implemented_harness(profile.commit.harness, field="commit.harness")
    artifact_dir_value = args.artifact_dir or profile.output.artifact_dir
    artifact_dir = Path(artifact_dir_value) if artifact_dir_value else default_artifact_dir()
    search_root = artifact_dir if artifact_dir_value else artifact_dir.parent
    initial_review_file = resolve_initial_review_file(args.initial_review_file, search_root)
    if initial_review_file is not None and not initial_review_file.is_file():
        raise FileNotFoundError(f"initial review file not found: {initial_review_file}")
    checks = tuple(args.check) if args.check is not None else profile.pipeline.checks
    review_reasoning_effort = (
        args.review_reasoning_effort
        or args.reasoning_effort
        or profile.review.reasoning_effort
    )
    remediation_reasoning_effort = (
        args.remediation_reasoning_effort
        or args.reasoning_effort
        or profile.remediation.reasoning_effort
    )
    triage_reasoning_effort = args.triage_reasoning_effort or profile.triage.reasoning_effort
    commit_reasoning_effort = args.commit_reasoning_effort or remediation_reasoning_effort
    review_model = args.review_model or args.model or profile.review.model
    remediation_model = args.remediation_model or args.model or profile.remediation.model
    commit_message_model = (
        args.commit_message_model
        or profile.commit.message_model
        or remediation_model
        or args.model
        or review_model
    )
    commit_on_hook_failure = args.commit_on_hook_failure or profile.commit.on_hook_failure
    config = LoopConfig(
        base=pick(args.base, profile.pipeline.base, "main"),
        max_iterations=pick(args.max_iterations, profile.pipeline.max_iterations, 2),
        codex_bin=pick(args.codex_bin, profile.runtime.codex_bin, "codex"),
        cwd=cwd,
        artifact_dir=artifact_dir,
        model=args.model,
        review_harness=profile.review.harness,
        remediation_harness=profile.remediation.harness,
        triage_harness=profile.triage.harness,
        commit_message_harness=profile.commit.harness,
        review_model=review_model,
        remediation_model=remediation_model,
        reasoning_effort=args.reasoning_effort,
        review_reasoning_effort=review_reasoning_effort,
        remediation_reasoning_effort=remediation_reasoning_effort,
        commit_after_remediation=commit_after_remediation,
        commit_message_model=commit_message_model,
        commit_message_prompt=args.commit_message_prompt or profile.commit.message_prompt,
        commit_message_prompt_overridden=(
            args.commit_message_prompt is not None or profile.commit.message_prompt is not None
        ),
        commit_on_hook_failure=commit_on_hook_failure,
        commit_reasoning_effort=commit_reasoning_effort,
        triage_enabled=profile.triage.enabled,
        triage_model=profile.triage.model,
        triage_reasoning_effort=triage_reasoning_effort,
        triage_timeout_seconds=triage_timeout_seconds,
        triage_prompt=profile.triage.prompt,
        triage_on_invalid=profile.triage.on_invalid,
        exec_sandbox=pick(args.exec_sandbox, profile.runtime.exec_sandbox, "workspace-write"),
        exec_color=pick(args.exec_color, profile.runtime.exec_color, "never"),
        full_auto=pick(args.full_auto, profile.runtime.full_auto, True),
        exec_json=pick(args.exec_json, profile.runtime.exec_json, False),
        output_last_message=pick(args.output_last_message, profile.runtime.output_last_message, True),
        dry_run=args.dry_run,
        final_review=pick(args.final_review, profile.pipeline.final_review, True),
        max_remediation_input_chars=pick(
            args.max_remediation_input_chars,
            profile.runtime.max_remediation_input_chars,
            200_000,
        ),
        terminal_excerpt_chars=pick(
            args.terminal_excerpt_chars,
            profile.runtime.terminal_excerpt_chars,
            4_000,
        ),
        timeout_seconds=timeout_seconds,
        review_timeout_seconds=review_timeout_seconds,
        remediation_timeout_seconds=remediation_timeout_seconds,
        debug_status_detection=pick(
            args.debug_status_detection,
            profile.output.debug_status_detection,
            False,
        ),
        progress=not pick(args.quiet_progress, profile.output.quiet_progress, False),
        progress_style=pick(args.progress_style, profile.output.progress_style, "compact"),
        terminal_title=pick(args.terminal_title, profile.output.terminal_title, False),
        initial_review_file=initial_review_file,
        check_commands=checks,
        profile_name=args.profile,
    )
    return config, (args.summary_format or profile.output.summary_format)


def profile_from_loop_config(
    name: str,
    config: LoopConfig,
    *,
    summary_format: str,
    description: str = "",
    include_artifact_dir: bool = False,
    timeout_seconds: float | None = None,
) -> profiles.Profile:
    saved_timeout_seconds = (
        timeout_seconds if timeout_seconds is not None else config.review_timeout_seconds
    )
    saved_remediation_timeout_seconds = (
        timeout_seconds if timeout_seconds is not None else config.remediation_timeout_seconds
    )
    saved_triage_timeout_seconds = (
        timeout_seconds
        if timeout_seconds is not None and config.triage_enabled
        else config.triage_timeout_seconds
    )
    return profiles.Profile(
        name=name,
        description=description,
        pipeline=profiles.PipelineConfig(
            base=config.base,
            max_iterations=config.max_iterations,
            final_review=config.final_review,
            checks=config.check_commands,
        ),
        review=profiles.PhaseConfig(
            harness=config.review_harness,
            model=config.review_model or config.model,
            reasoning_effort=config.review_reasoning_effort or config.reasoning_effort,
            timeout_seconds=saved_timeout_seconds,
        ),
        triage=profiles.TriageConfig(
            enabled=config.triage_enabled,
            harness=config.triage_harness,
            model=config.triage_model,
            reasoning_effort=config.triage_reasoning_effort,
            timeout_seconds=saved_triage_timeout_seconds,
            prompt=config.triage_prompt,
            on_invalid=config.triage_on_invalid,
        ),
        remediation=profiles.PhaseConfig(
            harness=config.remediation_harness,
            model=config.remediation_model or config.model,
            reasoning_effort=config.remediation_reasoning_effort or config.reasoning_effort,
            timeout_seconds=saved_remediation_timeout_seconds,
        ),
        commit=profiles.CommitConfig(
            enabled=config.commit_after_remediation,
            harness=config.commit_message_harness,
            message_model=config.commit_message_model,
            message_prompt=config.commit_message_prompt,
            on_hook_failure=config.commit_on_hook_failure,
        ),
        output=profiles.OutputConfig(
            summary_format=summary_format,
            debug_status_detection=config.debug_status_detection,
            progress_style=config.progress_style,
            quiet_progress=not config.progress,
            terminal_title=config.terminal_title,
            artifact_dir=str(config.artifact_dir) if include_artifact_dir else None,
        ),
        runtime=profiles.RuntimeConfig(
            codex_bin=config.codex_bin,
            exec_sandbox=config.exec_sandbox,
            exec_color=config.exec_color,
            exec_json=config.exec_json,
            output_last_message=config.output_last_message,
            full_auto=config.full_auto,
            max_remediation_input_chars=config.max_remediation_input_chars,
            terminal_excerpt_chars=config.terminal_excerpt_chars,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "bundle-bug-report":
        return bundle_bug_report_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "suppress":
        return suppress_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "replay":
        return replay_main(raw_argv[1:])
    if raw_argv and raw_argv[0] in {"doctor", "preflight"}:
        return doctor_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "config":
        return config_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "history":
        return history_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "ui":
        from code_review_loop import tui

        return tui.main(raw_argv[1:])

    args = parse_args(raw_argv)
    try:
        config, summary_format = build_loop_config(args, Path.cwd())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.save_profile:
        profile = profile_from_loop_config(
            args.save_profile,
            config,
            summary_format=summary_format,
            description=f"Saved from RevRem CLI on {datetime.now(UTC).date().isoformat()}",
            include_artifact_dir=args.artifact_dir is not None,
            timeout_seconds=args.timeout_seconds,
        )
        try:
            path = profiles.write_project_profile(
                profile,
                cwd=Path.cwd(),
                force=args.save_profile_force,
            )
        except FileExistsError as exc:
            print(f"ERROR: {exc}; pass --save-profile-force to replace it", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"ERROR: could not save project profile: {exc}", file=sys.stderr)
            return 1
        print(f"saved {args.save_profile} in {path}")
        return 0

    try:
        summary = run_loop(config)
    except RunLoopFailed as exc:
        summary = exc.summary
        if not args.dry_run and not args.no_run_history and summary.get("run_id"):
            try:
                append_run_history(summary, config)
            except OSError as history_exc:
                print(f"WARNING: could not write run history: {history_exc}", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - signal path
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - command-line reporting path
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.dry_run and not args.no_run_history and summary.get("run_id"):
        try:
            append_run_history(summary, config)
        except OSError as exc:
            print(f"WARNING: could not write run history: {exc}", file=sys.stderr)

    if summary_format in {"text", "both"}:
        print(format_terminal_summary(summary))
    if summary_format in {"json", "both"}:
        if summary_format == "both":
            print()
        print(json.dumps(summary, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    return 0 if summary.get("final_status") == "clear" else 2


def parse_suppress_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem suppress",
        description="Manage explicit finding suppressions.",
    )
    parser.add_argument("--scope", choices=suppressions.SCOPES, default="repo")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add or replace a suppression.")
    add.add_argument("fingerprint")
    add.add_argument("--summary", required=True)
    add.add_argument("--rationale", required=True)
    add.add_argument("--severity", choices=suppressions.SEVERITIES, default="medium")
    add.add_argument("--expires", default=None)
    add.add_argument("--critical-override", action="store_true")
    add.add_argument("--created-by", default=None)

    remove = subparsers.add_parser("remove", help="Remove a suppression.")
    remove.add_argument("fingerprint")

    check = subparsers.add_parser("check", help="Exit 0 when a fingerprint is suppressed.")
    check.add_argument("fingerprint")

    subparsers.add_parser("list", help="List suppressions.")
    subparsers.add_parser("expire", help="Remove expired suppressions.")
    return parser.parse_args(argv)


def suppress_main(argv: Sequence[str]) -> int:
    args = parse_suppress_args(argv)
    path = _suppression_path_for_scope(args.scope, Path.cwd())
    audit_path = _suppression_audit_path_for_scope(args.scope, Path.cwd())
    try:
        if args.command == "add":
            entry = suppressions.make_entry(
                fingerprint=args.fingerprint,
                summary=args.summary,
                rationale=args.rationale,
                severity=args.severity,
                scope=args.scope,
                expires_at=args.expires,
                critical_override=args.critical_override,
                created_by=args.created_by,
            )
            suppressions.add_entry(path, entry, audit_path=audit_path)
            print(f"added {entry.fingerprint} to {path}")
            return 0
        if args.command == "remove":
            if not suppressions.remove_entry(path, args.fingerprint, audit_path=audit_path):
                print(f"ERROR: suppression not found: {args.fingerprint}", file=sys.stderr)
                return 2
            print(f"removed {args.fingerprint} from {path}")
            return 0
        if args.command == "expire":
            count = suppressions.expire_entries(path, audit_path=audit_path)
            print(f"expired {count} suppression(s) from {path}")
            return 0
        if args.command == "check":
            matches = suppressions.load_effective_suppressions(Path.cwd())
            match = matches.get(args.fingerprint)
            if match is None:
                return 2
            if args.format == "json":
                print(json.dumps(asdict(match.entry), indent=2, sort_keys=True))
            else:
                print(f"suppressed {args.fingerprint} via {match.source_path}")
            return 0
        if args.command == "list":
            entries = suppressions.load_entries(path)
            if args.format == "json":
                print(json.dumps([asdict(entry) for entry in entries], indent=2, sort_keys=True))
            else:
                for entry in entries:
                    expires = f" expires={entry.expires_at}" if entry.expires_at else ""
                    print(f"{entry.fingerprint} {entry.severity_at_suppression} {entry.summary}{expires}")
            return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled suppress command: {args.command}")


def _suppression_path_for_scope(scope: str, cwd: Path) -> Path:
    if scope == "repo":
        return suppressions.repo_suppressions_path(cwd)
    return suppressions.user_suppressions_path()


def _suppression_audit_path_for_scope(scope: str, cwd: Path) -> Path:
    if scope == "repo":
        return suppressions.repo_audit_path(cwd)
    return suppressions.user_audit_path()


def config_main(argv: Sequence[str]) -> int:
    args = parse_config_args(argv)
    try:
        output_format = getattr(args, "format", None)
        if args.command == "list":
            items = profiles.profile_list_items(cwd=Path.cwd())
            if (output_format or "text") == "json":
                print(
                    json.dumps(
                        [profiles.profile_list_item_to_dict(item) for item in items],
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                for item in items:
                    print(_format_profile_list_item(item))
            return 0
        if args.command == "show":
            if output_format == "text":
                print(
                    "ERROR: 'text' format is not supported for 'show'. Use 'toml' or 'json'.",
                    file=sys.stderr,
                )
                return 1
            profile = profiles.resolve_profile(
                args.name,
                cwd=Path.cwd(),
                require_implemented=False,
            )
            if (output_format or "toml") == "json":
                print(profiles.profile_to_json(profile), end="")
            else:
                print(profiles.profile_to_toml(profile), end="")
            return 0
        if args.command == "new":
            profile = new_profile_from_args(args)
            path = profiles.write_user_profile(profile, force=args.force)
            print(f"created {args.name} in {path}")
            return 0
        if args.command == "edit":
            path = edit_profile_config(args.name, cwd=Path.cwd())
            print(f"edited {args.name} in {path}")
            return 0
        if args.command == "clone":
            path = profiles.clone_user_profile(
                args.source,
                args.target,
                cwd=Path.cwd(),
                force=args.force,
            )
            print(f"cloned {args.source} to {args.target} in {path}")
            return 0
        if args.command == "delete":
            if not args.yes:
                print("ERROR: pass --yes to delete a profile non-interactively", file=sys.stderr)
                return 1
            path = profiles.delete_user_profile(args.name)
            print(f"deleted {args.name} from {path}")
            return 0
        if args.command == "export":
            profile = profiles.resolve_profile(
                args.name,
                cwd=Path.cwd(),
                require_implemented=False,
            )
            print(profiles.profile_to_toml(profile, include_wrapper=True), end="")
            return 0
        if args.command == "import":
            path = profiles.import_user_profiles(Path(args.path), force=args.force)
            print(f"imported profiles into {path}")
            return 0
        if args.command == "doctor":
            profile_names = [item.name for item in profiles.list_profiles(cwd=Path.cwd())]
            info: dict[str, object] = {
                "user_config": str(profiles.user_config_path()),
                "project_config": str(profiles.project_config_path(Path.cwd())),
                "profiles": profile_names,
            }
            if args.profile:
                info["resolved_profile"] = profiles.profile_to_dict(
                    profiles.resolve_profile(
                        args.profile,
                        cwd=Path.cwd(),
                        require_implemented=False,
                    )
                )
            if (output_format or "text") == "json":
                print(json.dumps(info, indent=2, sort_keys=True))
            else:
                print(f"user_config: {info['user_config']}")
                print(f"project_config: {info['project_config']}")
                print("profiles: " + ", ".join(profile_names))
                if "resolved_profile" in info:
                    print(f"resolved_profile: {json.dumps(info['resolved_profile'], indent=2)}")
            return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled config command: {args.command}")


def _format_profile_list_item(item: profiles.ProfileListItem) -> str:
    desc = f" - {item.description}" if item.description else ""
    details: list[str] = []
    if item.source:
        details.append(item.source)
    details.append(f"last used {item.last_used_at or 'never'}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"{item.name}{desc}{suffix}"


def bundle_bug_report_main(argv: Sequence[str]) -> int:
    args = parse_bundle_bug_report_args(argv)
    if args.no_redact and not args.i_understand_the_risks:
        print("ERROR: --no-redact requires --i-understand-the-risks", file=sys.stderr)
        return 4
    try:
        result = bug_bundle.create_bug_bundle(
            bug_bundle.BundleOptions(
                run_dir=Path(args.run_dir),
                output_path=Path(args.output) if args.output else None,
                include_raw_transcripts=args.include_raw_transcripts,
                redact=not args.no_redact,
            )
        )
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(str(result.output_path))
    return 0


def parse_replay_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem replay",
        description="Replay a RevRem run from events.jsonl without invoking a model.",
    )
    parser.add_argument("run_dir", help="Run directory containing events.jsonl.")
    parser.add_argument("--renderer", choices=("compact",), default="compact")
    return parser.parse_args(argv)


def replay_main(argv: Sequence[str]) -> int:
    args = parse_replay_args(argv)
    path = Path(args.run_dir) / events.EVENTS_FILENAME
    try:
        records, truncated = events.read_events(path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(events.render_compact(records), end="")
    return 1 if truncated else 0


def doctor_main(argv: Sequence[str]) -> int:
    args = parse_doctor_args(argv)
    try:
        profile = profile_or_default(args.profile, Path.cwd(), require_implemented=False)
    except (FileNotFoundError, ValueError) as exc:
        issues = [
            diagnostics.DiagnosticIssue(
                code="revrem.preflight.profile_error",
                severity="blocking",
                message="RevRem profile configuration could not be resolved.",
                hint=str(exc),
                evidence={"profile": args.profile},
            )
        ]
    else:
        artifact_dir = _doctor_artifact_dir(args, profile)
        issues = diagnostics.run_doctor(
            diagnostics.DoctorConfig(
                cwd=Path.cwd(),
                base=args.base if args.base is not None else profile.pipeline.base,
                artifact_dir=artifact_dir,
                artifact_dir_is_default=args.artifact_dir is None and profile.output.artifact_dir is None,
                codex_bin=args.codex_bin if args.codex_bin is not None else profile.runtime.codex_bin,
                check_commands=tuple(args.check) if args.check is not None else profile.pipeline.checks,
                commit_after_remediation=args.commit_after_remediation or profile.commit.enabled,
            )
        )
        issues.extend(_suppression_doctor_issues(Path.cwd()))
    output_format = args.format or ("text" if sys.stdout.isatty() else "json")
    if output_format == "json":
        print(diagnostics.doctor_json(issues), end="")
    else:
        print(diagnostics.doctor_text(issues), end="")
    if diagnostics.has_blocking_issue(issues):
        return 4
    if args.strict and diagnostics.has_warning_issue(issues):
        return 6
    return 0


def _suppression_doctor_issues(cwd: Path) -> list[diagnostics.DiagnosticIssue]:
    issues: list[diagnostics.DiagnosticIssue] = []
    for path in (suppressions.user_suppressions_path(), suppressions.repo_suppressions_path(cwd)):
        try:
            expired, unsupported = suppressions.stale_entries(path)
        except ValueError as exc:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.suppressions.invalid_file",
                    severity="warn",
                    message="A suppression file could not be parsed.",
                    hint=str(exc),
                    evidence={"path": str(path)},
                )
            )
            continue
        if expired:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.suppressions.expired",
                    severity="warn",
                    message="A suppression file contains expired entries.",
                    hint="Run revrem suppress expire for the affected scope.",
                    evidence={
                        "path": str(path),
                        "fingerprints": [entry.fingerprint for entry in expired],
                    },
                )
            )
        if unsupported:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.suppressions.unsupported_fingerprint_version",
                    severity="warn",
                    message="A suppression file contains fingerprints RevRem cannot match.",
                    hint="Recreate these suppressions after the fingerprint migration tool exists.",
                    evidence={
                        "path": str(path),
                        "fingerprints": [entry.fingerprint for entry in unsupported],
                    },
                )
            )
    return issues


def _doctor_artifact_dir(args: argparse.Namespace, profile: profiles.Profile) -> Path:
    artifact_dir = args.artifact_dir if args.artifact_dir is not None else profile.output.artifact_dir
    if artifact_dir is not None:
        return Path(artifact_dir)
    return default_artifact_dir()


def history_main(argv: Sequence[str]) -> int:
    args = parse_history_args(argv)
    try:
        output_format = getattr(args, "format", None) or "text"
        if args.command == "list":
            if args.limit < 1:
                raise ValueError("--limit must be at least 1")
            records = run_history.read_history(limit=args.limit)
            if output_format == "json":
                print(json.dumps(records, indent=2, sort_keys=True))
            else:
                if not records:
                    print("No RevRem run history found.")
                    return 0
                for record in records:
                    run_id = record.get("run_id") or "<unknown>"
                    status = record.get("final_status") or "unknown"
                    reason = record.get("stopped_reason") or "unknown"
                    base = record.get("base") or "unknown"
                    artifact_dir = record.get("artifact_dir") or ""
                    print(f"{run_id} {status} ({reason}) base={base} artifacts={artifact_dir}")
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled history command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
