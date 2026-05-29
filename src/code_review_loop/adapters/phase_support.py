"""Shared phase-side-effect helpers for adapter implementations.

This module is intentionally below ``code_review_loop.runner`` in the dependency
graph. Phase adapters import it for progress, artifact, timeout, budget, and
commit-message helpers without reaching back into the CLI loop driver.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import textwrap
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from code_review_loop import artifacts, budgets, harnesses, progress
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RunContext
from code_review_loop.core.review_interpretation import (
    extract_finding_blocks,
    extract_review_summary,
    strip_finding_priority,
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

COMMIT_HOOK_FAILURE_RE = re.compile(
    r"\b("
    r"pre-commit|pre-push|commit hook|hook failed|"
    r"mypy|ruff|black|flake8|eslint|prettier|detect-secrets|"
    r"files? were modified by this hook|found \d+ errors?"
    r")\b",
    re.IGNORECASE,
)
CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\([A-Za-z0-9_.-]+\))?!?:\s+\S.+$"
)
REVREM_COMMIT_SUFFIX = " (RevRem)"
MAX_COMMIT_SUBJECT_LEN = 120

_RICH_UNAVAILABLE_WARNED = False


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


def _timeout_stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _combined_output(result: CommandResult) -> str:
    parts = []
    if result.stdout:
        parts.append(result.stdout.rstrip())
    if result.stderr:
        parts.append("\n[stderr]\n" + result.stderr.rstrip())
    return "\n".join(parts).strip() + "\n"


def write_artifact(path: Path, content: str) -> None:
    artifacts.write_text_artifact(path, content)


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


def compact_progress_label(label: str) -> str:
    if label in {"initial", "review-initial"}:
        return "init"
    if label in {"final", "review-final"}:
        return "fin"
    if label.startswith("review-"):
        return label.removeprefix("review-")
    return label


def compact_progress_prefix(phase: str, label: str) -> str:
    timestamp = datetime.now().strftime("%H:%M:%S")  # det-exempt: human-display timestamp
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


def progress_log(config: LoopConfig, message: str) -> None:
    if not config.progress:
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")  # det-exempt: human-display timestamp
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


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


def resolved_phase_detail(
    command: list[str],
    *,
    harness: str,
    model: str | None,
    reasoning_effort: str | None,
    timeout_seconds: float | None,
    sandbox: str | None = None,
    contract: str | None = None,
    source: str | None = None,
) -> str:
    fields = [f"harness={harness}"]
    if model:
        fields.append(f"model={model}")
    if reasoning_effort:
        fields.append(f"effort={reasoning_effort}")
    if timeout_seconds is not None:
        fields.append(f"timeout={timeout_seconds:g}")
    if sandbox:
        fields.append(f"sandbox={sandbox}")
    if contract:
        fields.append(f"contract={contract}")
    if source:
        fields.append(f"source={source}")
    return f"{shlex.join(command)} [{' '.join(fields)}]"


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
        priority, title = strip_finding_priority(block[0])
        print_progress_message(config, "review", label, title, head=f"{priority:<7}")
        for detail in block[1:]:
            progress_continuation(config, "review", label, detail, indent=COMPACT_PROGRESS_DETAIL_INDENT)
    return True


def set_phase_terminal_title(config: LoopConfig, phase: str, label: str) -> None:
    from code_review_loop.adapters.terminal import (
        set_phase_terminal_title as _set_phase_terminal_title,
    )

    _set_phase_terminal_title(config, phase, label)


def terminal_iteration_label(label: str, max_iterations: int) -> str:
    if label.isdecimal():
        return f"{label}/{max_iterations}"
    if label == "final":
        return "final"
    return label


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


def lexical_git_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None
