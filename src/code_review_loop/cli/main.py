"""Top-level CLI entrypoint and subcommand dispatch."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from code_review_loop import redaction
from code_review_loop.cli.args import parse_args
from code_review_loop.cli.commands.profile import save_profile_from_args
from code_review_loop.cli.config_builder import build_loop_config
from code_review_loop.cli.config_support import (
    PendingReviewCandidate,
    current_git_state_for_latest,
    find_pending_review_candidate,
)
from code_review_loop.cli.exit import map_application_call
from code_review_loop.prompts_composer import trim_for_prompt


def main(argv: Sequence[str] | None = None) -> int:
    from code_review_loop import application
    from code_review_loop.cli.commands.registry import dispatch_or_none

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    dispatch_result = dispatch_or_none(raw_argv)
    if dispatch_result is not None:
        return dispatch_result

    args = parse_args(raw_argv)
    try:
        config, summary_format = build_loop_config(args, Path.cwd())
        config = replace(config, command_line=("revrem", *_redacted_argv(raw_argv)))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1  # outcome-exempt: configuration failed before RunOutcome exists
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1  # outcome-exempt: configuration failed before RunOutcome exists

    if args.save_profile:
        return save_profile_from_args(
            args,
            config,
            summary_format=summary_format,
            cwd=Path.cwd(),
        )

    pending_result = _apply_pending_review_choice(config, args)
    if pending_result is None:
        return 130  # outcome-exempt: operator cancelled before RunOutcome exists
    config = pending_result

    app_exit = map_application_call(lambda: application.run_review_loop(config))
    summary = app_exit.summary
    if app_exit.error:
        if not args.dry_run and not args.no_run_history and summary.get("run_id"):
            try:
                application.append_run_history(summary, config)
            except OSError as history_exc:
                print(f"WARNING: could not write run history: {history_exc}", file=sys.stderr)
        if app_exit.cancelled:
            print(app_exit.error, file=sys.stderr)
        else:
            print(f"ERROR: {app_exit.error}", file=sys.stderr)
        return app_exit.exit_code

    if not args.dry_run and not args.no_run_history and summary.get("run_id"):
        try:
            application.append_run_history(summary, config)
        except OSError as exc:
            print(f"WARNING: could not write run history: {exc}", file=sys.stderr)

    if summary_format in {"text", "both"}:
        print(application.format_terminal_summary(summary))
    if summary_format in {"json", "both"}:
        if summary_format == "both":
            print()
        print(json.dumps(summary, indent=2, sort_keys=True))
    if args.dry_run:
        return 0  # outcome-exempt: dry-run summary is intentionally non-terminal
    return app_exit.exit_code


def _apply_pending_review_choice(config, args):
    if config.initial_review_file is not None:
        return config
    mode = args.pending_review
    if mode is None:
        mode = "prompt" if sys.stdin.isatty() and sys.stdout.isatty() else "ignore"
    if mode == "ignore":
        return config
    candidate = _pending_review_candidate(config)
    if candidate is None:
        return config
    if mode == "auto":
        return replace(config, initial_review_file=candidate.path)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return config
    return _prompt_for_pending_review(config, candidate)


def _pending_review_candidate(config) -> PendingReviewCandidate | None:
    search_root = config.artifact_dir.parent if config.artifact_dir_is_default else config.artifact_dir
    return find_pending_review_candidate(
        search_root,
        current_git_state=current_git_state_for_latest(config.cwd, config.base),
    )


def _prompt_for_pending_review(config, candidate: PendingReviewCandidate):
    _print_pending_review_summary(candidate)
    while True:
        print(
            "Use this review? [u]se / [d]etails / [f]resh / [c]ancel: ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        choice = input().strip().lower()
        if choice in {"u", "use", "y", "yes"}:
            return replace(config, initial_review_file=candidate.path)
        if choice in {"d", "detail", "details", "more"}:
            print(
                "\nPending review detail:\n"
                f"{trim_for_prompt(candidate.excerpt, config.terminal_excerpt_chars)}\n"
                f"Artifact: {candidate.path}\n",
                file=sys.stderr,
            )
            continue
        if choice in {"f", "fresh", "n", "no", "skip"}:
            return config
        if choice in {"c", "cancel", "q", "quit"}:
            print("Cancelled before provider calls.", file=sys.stderr)
            return None
        print("Choose u, d, f, or c.", file=sys.stderr)


def _print_pending_review_summary(candidate: PendingReviewCandidate) -> None:
    status_parts = [
        part
        for part in (candidate.final_status, candidate.stopped_reason, candidate.error)
        if part
    ]
    status = " · ".join(status_parts) if status_parts else "previous non-clear run"
    excerpt = trim_for_prompt(candidate.excerpt, 500).replace("\n", " ").strip()
    print(
        "RevRem found compatible pending review feedback before starting a new review.\n"
        f"Review: {candidate.path}\n"
        f"Run: {candidate.run_dir}\n"
        f"Status: {status}",
        file=sys.stderr,
    )
    if excerpt:
        print(f"Excerpt: {excerpt}", file=sys.stderr)


def _redacted_argv(argv: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False
    sensitive_flags = {"--commit-message-prompt", "--triage-prompt"}
    for item in argv:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if item in sensitive_flags:
            redacted.append(item)
            redact_next = True
            continue
        if any(item.startswith(f"{flag}=") for flag in sensitive_flags):
            flag, _sep, _value = item.partition("=")
            redacted.append(f"{flag}=<redacted>")
            continue
        redacted.append(redaction.redact_text(item).text)
    return tuple(redacted)
