#!/usr/bin/env python3
"""Run a bounded Codex review/remediation loop against a base branch."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

STATUS_RE = re.compile(r"^\s*REVIEW_STATUS:\s*(clear|findings)\s*$", re.IGNORECASE | re.MULTILINE)
CODEX_FINDING_RE = re.compile(r"^\s*-\s*\[P[0-3]\]\s+", re.MULTILINE)
CODEX_FINDING_LINE_RE = re.compile(r"^\s*-\s*(\[P[0-3]\]\s+.+)$")
REVIEW_COMMENTS_HEADING_RE = re.compile(
    r"^\s*(full\s+)?review comments?:\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PROGRESS_PHASE_CODES = {
    "check": "chk",
    "remediate": "rem",
    "review": "rev",
}
COMPACT_PROGRESS_DETAIL_INDENT = 7
DEFAULT_TERMINAL_COLUMNS = 120
DEFAULT_TIMEOUT_SECONDS = 300

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
    review_model: str | None = None
    remediation_model: str | None = None
    reasoning_effort: str | None = None
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
    debug_status_detection: bool = False
    progress: bool = True
    progress_style: str = "compact"
    terminal_title: bool = False
    initial_review_file: Path | None = None
    check_commands: tuple[str, ...] = field(default_factory=tuple)


Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]

TERMINAL_TITLE_SAVE = "\033]22;0\007"
TERMINAL_TITLE_RESTORE = "\033]23;0\007"


def terminal_title_supported(config: LoopConfig) -> bool:
    return config.terminal_title and sys.stderr.isatty()


def sanitize_terminal_title(value: str) -> str:
    return value.replace("\033", "").replace("\007", "").replace("\n", " ").replace("\r", " ")


def write_terminal_control(sequence: str) -> None:
    sys.stderr.write(sequence)
    sys.stderr.flush()


def set_terminal_title(config: LoopConfig, title: str) -> None:
    if not terminal_title_supported(config):
        return
    write_terminal_control(f"\033]0;{sanitize_terminal_title(title)}\007")


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
    if not terminal_title_supported(config):
        yield
        return
    # There is no reliable cross-terminal way to read the current title. Xterm-
    # compatible terminals support a title stack, which gives the desired
    # save/restore behavior without querying terminal state.
    write_terminal_control(TERMINAL_TITLE_SAVE)
    try:
        yield
    finally:
        write_terminal_control(TERMINAL_TITLE_RESTORE)


def progress_log(config: LoopConfig, message: str) -> None:
    if not config.progress:
        return
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    timestamp = datetime.now(UTC).strftime("%H:%M:%S")
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
    if config.progress_style == "verbose":
        suffix = f": {detail}" if detail else ""
        progress_log(config, f"{phase} {label}: {status}{suffix}")
        return
    if detail:
        print_compact_progress(phase, label, detail, head=f"{status}: ")
    else:
        print_compact_progress(phase, label, status)


def progress_continuation(config: LoopConfig, phase: str, label: str, text: str, indent: int = 2) -> None:
    if not config.progress:
        return
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
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        return CommandResult(
            args=list(args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            args=list(args),
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout_seconds} seconds",
        )


def detect_review_status(output: str) -> str:
    """Return clear/findings/unknown for Codex review output."""
    actionable_output = actionable_review_output(output)
    match = STATUS_RE.search(actionable_output)
    if match:
        return match.group(1).lower()

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
    clear_phrases = (
        "did not find any discrete, actionable bugs",
        "did not find any actionable bugs",
        "no discrete, actionable bugs",
        "no actionable bugs",
    )
    if any(phrase in normalized for phrase in clear_phrases):
        return "clear"
    return "unknown"


def review_status_diagnostics(output: str) -> dict[str, object]:
    """Return compact, targeted diagnostics for review-status classification."""
    actionable_output = actionable_review_output(output)
    stderr_present = "\n[stderr]\n" in output
    explicit_status = STATUS_RE.search(actionable_output)
    finding_lines = CODEX_FINDING_RE.findall(actionable_output)
    normalized = actionable_output.lower()
    clear_phrase_present = any(
        phrase in normalized
        for phrase in (
            "did not find any discrete, actionable bugs",
            "did not find any actionable bugs",
            "no discrete, actionable bugs",
            "no actionable bugs",
        )
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
    if config.progress_style == "verbose":
        progress_log(config, f"{phase} {label}: {head}{text}")
        return
    print_compact_progress(phase, label, text, head=head)


def strip_finding_priority(finding: str) -> tuple[str, str]:
    match = re.match(r"^(\[P[0-3]\])\s+(.+)$", finding)
    if not match:
        return "", finding
    return match.group(1), match.group(2)


def codex_config_args(config: LoopConfig) -> list[str]:
    args: list[str] = []
    if config.reasoning_effort:
        # Codex parses -c values as TOML; the quotes are part of the TOML string
        # syntax, not shell quoting. subprocess.run() intentionally receives one
        # argv item such as model_reasoning_effort="low".
        args.extend(["-c", f'model_reasoning_effort="{config.reasoning_effort}"'])
    return args


def build_review_command(config: LoopConfig) -> list[str]:
    command = [config.codex_bin]
    command.extend(codex_config_args(config))
    model = config.review_model or config.model
    if model:
        command.extend(["--model", model])
    command.extend(["review", "--base", config.base])
    return command


def build_remediation_command(config: LoopConfig, output_last_message: Path | None = None) -> list[str]:
    command = [config.codex_bin, "exec"]
    command.extend(codex_config_args(config))
    if config.full_auto:
        command.append("--full-auto")
    command.extend(["--sandbox", config.exec_sandbox])
    command.extend(["--color", config.exec_color])
    if config.exec_json:
        command.append("--json")
    model = config.remediation_model or config.model
    if model:
        command.extend(["--model", model])
    if output_last_message:
        command.extend(["--output-last-message", str(output_last_message)])
    command.append("-")
    return command


def write_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
        result = runner(command, config.cwd, None, config.timeout_seconds)
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
        result = runner(command, config.cwd, prompt, config.timeout_seconds)
    write_artifact(config.artifact_dir / f"remediation-{iteration}.txt", _combined_output(result))
    if result.returncode != 0:
        progress_event(config, "remediate", str(iteration), "failed", f"exit {result.returncode}")
        raise RuntimeError(
            f"codex exec remediation failed for iteration {iteration}; "
            f"see {config.artifact_dir / f'remediation-{iteration}.txt'}"
        )
    progress_event(config, "remediate", str(iteration), "done")
    return result


def run_checks(config: LoopConfig, runner: Runner, iteration: int) -> list[CommandResult]:
    results: list[CommandResult] = []
    for index, check in enumerate(config.check_commands, start=1):
        command = shlex.split(check)
        progress_event(config, "check", f"{iteration}.{index}", "start", check)
        if config.dry_run:
            result = CommandResult(command, 0, stdout=f"DRY_RUN check skipped: {check}\n")
        else:
            result = runner(command, config.cwd, None, config.timeout_seconds)
        results.append(result)
        write_artifact(
            config.artifact_dir / f"check-{iteration}-{index}.txt",
            _combined_output(result),
        )
        if result.returncode == 0:
            progress_event(config, "check", f"{iteration}.{index}", "passed")
        else:
            progress_event(config, "check", f"{iteration}.{index}", "failed", f"exit {result.returncode}")
    return results


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
        "last_messages": [
            str(path)
            for path in files
            if path.name.startswith("remediation-") and "last-message" in path.name
        ],
        "checks": [str(path) for path in files if path.name.startswith("check-")],
        "diagnostics": [str(path) for path in files if path.name.endswith("-status.json")],
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
            if path.is_file()
        ),
        key=lambda path: (path.stat().st_mtime, path.parent.name),
    )
    if not candidates:
        raise FileNotFoundError(f"no review-final.txt found under {search_root}")
    return candidates[-1]


def run_loop(config: LoopConfig, runner: Runner = default_runner) -> dict[str, object]:
    with terminal_title_context(config):
        return _run_loop(config, runner)


def _run_loop(config: LoopConfig, runner: Runner = default_runner) -> dict[str, object]:
    if config.max_iterations < 1:
        raise ValueError("--max-iterations must be at least 1")

    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    iterations: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "base": config.base,
        "max_iterations": config.max_iterations,
        "artifact_dir": str(config.artifact_dir),
        "iterations": iterations,
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
            status, review = run_codex_review(
                config,
                runner,
                f"review-{iteration}",
                display_label=str(iteration),
            )
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
            run_remediation(config, runner, iteration, remediation_input)
        except Exception as exc:
            summary["final_status"] = "error"
            summary["stopped_reason"] = "remediation_failed"
            summary["error"] = str(exc)
            iterations[-1]["remediation_failed"] = True
            write_summary(config, summary)
            raise

        check_results = run_checks(config, runner, iteration)
        pending_check_failures = _format_check_failures(check_results)
        iterations[-1]["check_failures"] = sum(1 for result in check_results if result.returncode != 0)

    if config.final_review:
        status, final_review = run_codex_review(
            config,
            runner,
            "review-final",
            display_label="final",
        )
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
    else:
        # Status after the last remediation is not known without a review.
        summary["final_status"] = "unknown"
        summary["pending_check_failures"] = bool(pending_check_failures)
        summary["stopped_reason"] = "max_iterations_reached"

    write_summary(config, summary)
    return summary


def write_summary(config: LoopConfig, summary: dict[str, object]) -> None:
    add_artifact_paths(summary, config)
    write_artifact(config.artifact_dir / "summary.json", json.dumps(summary, indent=2, sort_keys=True))


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
            lines.append(f"  {iteration}: review={review_status}, {check_text}{failed}")

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
        summary_path = artifact_paths.get("summary")
        if summary_path:
            lines.append(f"JSON summary: {summary_path}")

    excerpt = str(summary.get("latest_review_excerpt") or "").strip()
    if excerpt:
        lines.append("")
        lines.append("Latest actionable review output:")
        lines.append(excerpt)

    if summary.get("error"):
        lines.append("")
        lines.append(f"Error: {summary['error']}")

    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded Codex review/remediation loop against a base branch.",
    )
    parser.add_argument("--base", default="main", help="Base branch passed to codex review.")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=2,
        help="Maximum remediation passes before stopping. Default: 2.",
    )
    parser.add_argument("--codex-bin", default="codex", help="Codex executable path/name.")
    parser.add_argument("--model", default=None, help="Optional model passed to both Codex review and remediation.")
    parser.add_argument("--review-model", default=None, help="Optional model override for codex review only.")
    parser.add_argument(
        "--remediation-model",
        default=None,
        help="Optional model override for codex exec remediation only.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high"),
        default=None,
        help="Optional Codex model_reasoning_effort override for review and remediation.",
    )
    parser.add_argument(
        "--exec-sandbox",
        default="workspace-write",
        choices=("read-only", "workspace-write", "danger-full-access"),
        help="Sandbox mode for codex exec remediation passes.",
    )
    parser.add_argument(
        "--exec-color",
        default="never",
        choices=("always", "never", "auto"),
        help="Color mode for codex exec remediation output. Default: never.",
    )
    parser.add_argument(
        "--exec-json",
        action="store_true",
        help="Pass --json to codex exec and capture JSONL event output.",
    )
    parser.add_argument(
        "--no-output-last-message",
        action="store_true",
        help="Do not pass --output-last-message to codex exec remediation passes.",
    )
    parser.add_argument(
        "--no-full-auto",
        action="store_true",
        help="Do not pass --full-auto to codex exec.",
    )
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        help="Verification command to run after each remediation pass. Repeatable.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Directory for review/remediation/check transcripts.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the loop shape without running Codex.")
    parser.add_argument(
        "--skip-final-review",
        action="store_true",
        help="Do not run the final review after the last remediation pass.",
    )
    parser.add_argument(
        "--max-remediation-input-chars",
        type=int,
        default=200_000,
        help="Maximum review/check text characters passed into each remediation prompt.",
    )
    parser.add_argument(
        "--terminal-excerpt-chars",
        type=int,
        default=4_000,
        help="Maximum latest-review characters shown in terminal text summaries.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Maximum seconds for each review, remediation, or check command. "
            "Use 0 to disable subprocess timeouts. Default: 300."
        ),
    )
    parser.add_argument(
        "--summary-format",
        choices=("text", "json", "both"),
        default="text",
        help="Summary format printed to stdout. Full JSON is always written to summary.json.",
    )
    parser.add_argument(
        "--debug-status-detection",
        action="store_true",
        help="Write per-review status-classification diagnostics next to review artifacts.",
    )
    parser.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Suppress timestamped progress logs on stderr.",
    )
    parser.add_argument(
        "--progress-style",
        choices=("compact", "verbose"),
        default="compact",
        help="Progress log style. Compact is easier to scan in terminals.",
    )
    parser.add_argument(
        "--terminal-title",
        action="store_true",
        help=(
            "Update the terminal window/tab title with the active review or remediation phase. "
            "Restores the previous title on exit in terminals with title-stack support."
        ),
    )
    parser.add_argument(
        "--initial-review-file",
        type=str,
        default=None,
        help="Start by remediating a previous review artifact. Use 'latest' for newest review-final.txt.",
    )
    return parser.parse_args(argv)


def default_artifact_dir() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("tmp") / "code-review-loop" / timestamp


def resolve_timeout_seconds(value: float) -> float | None:
    if value < 0:
        raise ValueError("--timeout-seconds must be 0 or greater")
    if value == 0:
        return None
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else default_artifact_dir()
    search_root = artifact_dir if args.artifact_dir else artifact_dir.parent
    try:
        initial_review_file = resolve_initial_review_file(args.initial_review_file, search_root)
        timeout_seconds = resolve_timeout_seconds(args.timeout_seconds)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if initial_review_file is not None and not initial_review_file.is_file():
        print(f"ERROR: initial review file not found: {initial_review_file}", file=sys.stderr)
        return 1
    config = LoopConfig(
        base=args.base,
        max_iterations=args.max_iterations,
        codex_bin=args.codex_bin,
        cwd=Path.cwd(),
        artifact_dir=artifact_dir,
        model=args.model,
        review_model=args.review_model,
        remediation_model=args.remediation_model,
        reasoning_effort=args.reasoning_effort,
        exec_sandbox=args.exec_sandbox,
        exec_color=args.exec_color,
        full_auto=not args.no_full_auto,
        exec_json=args.exec_json,
        output_last_message=not args.no_output_last_message,
        dry_run=args.dry_run,
        final_review=not args.skip_final_review,
        max_remediation_input_chars=args.max_remediation_input_chars,
        terminal_excerpt_chars=args.terminal_excerpt_chars,
        timeout_seconds=timeout_seconds,
        debug_status_detection=args.debug_status_detection,
        progress=not args.quiet_progress,
        progress_style=args.progress_style,
        terminal_title=args.terminal_title,
        initial_review_file=initial_review_file,
        check_commands=tuple(args.check),
    )

    try:
        summary = run_loop(config)
    except KeyboardInterrupt:  # pragma: no cover - signal path
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - command-line reporting path
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.summary_format in {"text", "both"}:
        print(format_terminal_summary(summary))
    if args.summary_format in {"json", "both"}:
        if args.summary_format == "both":
            print()
        print(json.dumps(summary, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    return 0 if summary.get("final_status") == "clear" else 2


if __name__ == "__main__":
    raise SystemExit(main())
