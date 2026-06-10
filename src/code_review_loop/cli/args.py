"""Argparse parsers for the RevRem CLI (REVREM-TASK-003 Wave C2a).

This module is the canonical home for command-line parser construction and the
shared choice tuples consumed by the CLI entrypoint.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from code_review_loop import __version__, profiles, suppressions
from code_review_loop.config import EXTERNAL_REVIEW_TRUNCATION_POLICIES

# Argparse choice tuples shared across parsers. Single source of truth so the
# parent ``cli`` package re-exports them rather than maintaining duplicates.
REASONING_EFFORT_CHOICES = ("minimal", "low", "medium", "high")
PROGRESS_STYLE_CHOICES = ("compact", "verbose", "rich")
COMMIT_ON_HOOK_FAILURE_CHOICES = profiles.COMMIT_ON_HOOK_FAILURE_CHOICES


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem",
        description="Run a bounded Codex review/remediation loop against a base branch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Triage/routing examples:\n"
            "  revrem --profile dogfood --triage --triage-contract v2 --routing\n"
            "  revrem --profile dogfood --routing --route gemini-pro\n"
            "  revrem --profile dogfood --no-triage --no-routing --dry-run --summary-format json\n"
            "  revrem --profile dogfood --no-allow-model-escalation\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--profile", default=None, help="Named profile from RevRem TOML config.")
    parser.add_argument("--base", default=None, help="Base branch passed to codex review.")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum remediation passes before stopping. Defaults to profile value or 2.",
    )
    parser.add_argument("--codex-bin", default=None, help="Codex executable path/name.")
    parser.add_argument(
        "--harness-bin",
        action="append",
        default=[],
        metavar="HARNESS=EXECUTABLE",
        help="Override an executable for a named harness, for example claude=/opt/bin/claude.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model passed to both Codex review and remediation.",
    )
    parser.add_argument(
        "--review-harness",
        default=None,
        help="Optional harness override for review only.",
    )
    parser.add_argument(
        "--review-model",
        default=None,
        help="Optional model override for codex review only.",
    )
    parser.add_argument(
        "--triage-model", default=None, help="Optional model override for triage only."
    )
    parser.add_argument(
        "--triage-harness",
        default=None,
        help="Optional harness override for triage only.",
    )
    parser.add_argument(
        "--commit-message-harness",
        "--commit-harness",
        dest="commit_message_harness",
        default=None,
        help=(
            "Optional harness override for read-only commit-message drafting. "
            "Alias: --commit-harness."
        ),
    )
    parser.add_argument(
        "--remediation-harness",
        "--remediate-harness",
        dest="remediation_harness",
        default=None,
        help=("Optional harness override for remediation only. Alias: --remediate-harness."),
    )
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
        help=(
            "Optional Codex model_reasoning_effort override for remediation only. "
            "Alias: --remediate-reasoning-effort."
        ),
    )
    parser.add_argument(
        "--commit-reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=None,
        help="Optional Codex model_reasoning_effort override for commit-message drafting only.",
    )
    triage_group = parser.add_mutually_exclusive_group()
    triage_group.add_argument(
        "--triage",
        dest="triage_enabled",
        action="store_true",
        default=None,
        help="Enable triage for this run, overriding the selected profile.",
    )
    triage_group.add_argument(
        "--no-triage",
        dest="triage_enabled",
        action="store_false",
        default=None,
        help="Disable triage for this run, overriding the selected profile.",
    )
    parser.add_argument(
        "--triage-contract",
        choices=("v1", "v2"),
        default=None,
        help="Optional triage contract override.",
    )
    parser.add_argument(
        "--triage-timeout-seconds",
        type=float,
        default=None,
        help="Maximum seconds for triage. Use 0 to disable triage timeout.",
    )
    routing_group = parser.add_mutually_exclusive_group()
    routing_group.add_argument(
        "--routing",
        dest="routing_enabled",
        action="store_true",
        default=None,
        help="Enable v2 routing for this run, overriding the selected profile.",
    )
    routing_group.add_argument(
        "--no-routing",
        dest="routing_enabled",
        action="store_false",
        default=None,
        help="Disable v2 routing for this run, overriding the selected profile.",
    )
    routing_strict_group = parser.add_mutually_exclusive_group()
    routing_strict_group.add_argument(
        "--routing-strict",
        dest="routing_strict",
        action="store_true",
        default=None,
        help="Fail when a selected routing route cannot resolve to an implemented harness.",
    )
    routing_strict_group.add_argument(
        "--no-routing-strict",
        dest="routing_strict",
        action="store_false",
        default=None,
        help="Allow routing fallback when a selected route is unavailable.",
    )
    routing_escalation_group = parser.add_mutually_exclusive_group()
    routing_escalation_group.add_argument(
        "--allow-model-escalation",
        dest="allow_model_escalation",
        action="store_true",
        default=None,
        help="Allow v2 routing to accept a model-proposed route above the policy route.",
    )
    routing_escalation_group.add_argument(
        "--no-allow-model-escalation",
        dest="allow_model_escalation",
        action="store_false",
        default=None,
        help="Reject model-proposed v2 routing escalation above the policy route.",
    )
    parser.add_argument(
        "--routing-default-route",
        "--route",
        dest="routing_default_route",
        default=None,
        help=(
            "Force v2 routing to use an existing route name from the selected profile. "
            "Alias: --route."
        ),
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
        help="Color mode for codex exec remediation output. Defaults to profile value or never.",
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
    parser.add_argument(
        "--trusted-repo",
        action="store_true",
        default=None,
        help="Explicitly trust repo-local prompt fragments.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the loop shape without running Codex.",
    )
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
        "--inner-check-retries",
        type=int,
        default=None,
        help=(
            "Retry remediation/checks inside the same iteration after failed "
            "post-remediation checks. Defaults to profile value or 0."
        ),
    )
    parser.add_argument(
        "--provider-retry-attempts",
        type=int,
        default=None,
        help=(
            "Attempts for transient non-Codex provider review/remediation failures. "
            "Includes the initial attempt. Defaults to profile value or 2."
        ),
    )
    parser.add_argument(
        "--provider-retry-backoff-seconds",
        type=float,
        default=None,
        help=(
            "Seconds to wait between transient non-Codex provider retry attempts. "
            "Defaults to profile value or 1.0."
        ),
    )
    parser.add_argument(
        "--external-review-input-chars",
        type=int,
        default=None,
        help="Maximum characters passed to prompted non-Codex review harnesses.",
    )
    parser.add_argument(
        "--external-review-warning-seconds",
        type=float,
        default=None,
        help=(
            "Elapsed seconds before long-running prompted review waiting "
            "messages include stronger diagnostics; 0 disables the warning."
        ),
    )
    parser.add_argument(
        "--external-review-truncation-policy",
        choices=EXTERNAL_REVIEW_TRUNCATION_POLICIES,
        default=None,
        help=(
            "How prompted non-Codex reviews handle oversized generated context: "
            "'warn' sends a bounded prompt and records coverage; 'fail' stops before "
            "accepting a truncated review."
        ),
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
            "Use 0 to disable subprocess timeouts. Defaults to profile value or 300."
        ),
    )
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=None,
        help="Maximum total run wall-clock seconds before RevRem stops before the next model call.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Maximum reported tokens for future cost-aware harnesses. Missing token data is recorded as null.",
    )
    parser.add_argument(
        "--max-usd",
        default=None,
        help="Maximum reported USD cost for future cost-aware harnesses. Missing cost data is recorded as null.",
    )
    parser.add_argument(
        "--soft-warn-fraction",
        type=float,
        default=None,
        help="Fraction of a configured ceiling that emits a warning event before stopping. Default: 0.8.",
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
            "compatible usable non-clear generated review; if none exists, start with a fresh review."
        ),
    )
    parser.add_argument(
        "--pending-review",
        choices=("prompt", "ignore", "auto"),
        default=None,
        help=(
            "What to do when startup discovers compatible pending review feedback and "
            "--initial-review-file was not supplied. Default: prompt in interactive "
            "terminals, ignore in non-interactive runs."
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
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero when warnings are present."
    )
    parser.add_argument("--profile", default=None, help="Resolve defaults from a named profile.")
    parser.add_argument(
        "--base", default=None, help="Base ref to validate. Defaults to profile/main."
    )
    parser.add_argument("--codex-bin", default=None, help="Codex executable path/name to validate.")
    parser.add_argument("--artifact-dir", default=None, help="Artifact directory to validate.")
    parser.add_argument(
        "--check",
        action="append",
        default=None,
        help="Check command to validate. Repeatable.",
    )
    parser.add_argument(
        "--validate-routes",
        action="store_true",
        help="Validate configured route harness executables even when profile routing is disabled.",
    )
    parser.add_argument(
        "--commit-after-remediation",
        action="store_true",
        default=None,
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


def parse_resume_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem resume",
        description="Validate whether a previous RevRem run is safe to resume.",
    )
    parser.add_argument("run_dir", help="Run directory containing summary.json and events.jsonl.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


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


def parse_replay_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem replay",
        description="Replay a RevRem run from events.jsonl without invoking a model.",
    )
    parser.add_argument("run_dir", help="Run directory containing events.jsonl.")
    parser.add_argument("--renderer", choices=("compact",), default="compact")
    return parser.parse_args(argv)


def parse_policy_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem policy",
        description="Inspect and lint routing policy.",
    )
    parser.add_argument("--format", choices=("text", "json"), default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint = subparsers.add_parser("lint", help="Lint routing rules and routes in a profile.")
    lint.add_argument("--profile", required=True)
    lint.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    lint.add_argument(
        "--executable-routes",
        action="store_true",
        help="Validate route fallback chains for implemented harness support even when routing is disabled.",
    )
    review = subparsers.add_parser("review", help="Summarize routing outcomes from run artifacts.")
    review.add_argument("--artifact-dir", required=True)
    review.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    return parser.parse_args(argv)


def parse_triage_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem triage",
        description="Inspect triage and routing artifacts.",
    )
    parser.add_argument("--format", choices=("text", "json"), default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    explain = subparsers.add_parser(
        "explain", help="Explain the routing decision for a run iteration."
    )
    explain.add_argument("run_dir")
    explain.add_argument("--iteration", type=int, default=1)
    explain.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    return parser.parse_args(argv)
