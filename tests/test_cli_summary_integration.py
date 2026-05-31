from __future__ import annotations

import tests.support.application_runner as runner_mod
from code_review_loop import artifacts, reporting
from code_review_loop.cli.main import _redacted_argv
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import format_terminal_summary


def test_summary_includes_latest_review_excerpt_and_artifact_paths(tmp_path):
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P1] Fix init\n",
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

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["latest_review_excerpt"] == "No findings."
    assert "artifact_paths" in summary
    assert summary["artifact_paths"]["summary"].endswith("summary.json")
    assert "phase_config" in summary
    assert summary["phase_config"]["review"]["harness"] == "codex"


def test_command_line_redacts_prompt_values():
    assert _redacted_argv(["--commit-message-prompt", "secret prompt", "--base", "main"]) == (
        "--commit-message-prompt",
        "<redacted>",
        "--base",
        "main",
    )
    assert _redacted_argv(["--commit-message-prompt=secret prompt"]) == (
        "--commit-message-prompt=<redacted>",
    )


def test_command_line_redacts_secret_like_tokens(monkeypatch):
    monkeypatch.setenv("HOME", "/home/example-user")
    assert _redacted_argv([
        "--api-token",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",  # pragma: allowlist secret
        "--path=/home/example-user/project",
        "--opaque=0123456789abcdef0123456789abcdef",  # pragma: allowlist secret
    ]) == (
        "--api-token",
        "[REDACTED:github-token]",
        "--path=[REDACTED:home]/project",
        "--opaque=[REDACTED:generic-token]",
    )


def test_summary_collects_commit_message_fallback_artifacts(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifacts.write_json_artifact(
        artifact_dir,
        "commit-2-message-fallback.json",
        {"iteration": 2, "reason": "model_drafting_failed", "subject": "fix(core): x (RevRem)"},
    )
    summary: dict[str, object] = {}

    reporting.add_artifact_paths(summary, LoopConfig(artifact_dir=artifact_dir))

    assert summary["commit_message_fallbacks"][0] | {"schema_version": "1.0"} == {
        "iteration": 2,
        "reason": "model_drafting_failed",
        "subject": "fix(core): x (RevRem)",
        "schema_version": "1.0",
        "artifact": str(artifact_dir / "commit-2-message-fallback.json"),
    }


def test_terminal_summary_surfaces_latest_findings_and_paths():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "iterations": [
            {"iteration": 1, "review_status": "findings", "check_failures": 0},
            {
                "iteration": 2,
                "review_status": "findings",
                "check_failures": 1,
                "checks": [
                    {
                        "command": "./.venv/bin/ruff check .",
                        "status": "passed",
                        "artifact": "check-2-1.txt",
                    },
                    {
                        "command": "./.venv/bin/pytest -q",
                        "status": "failed",
                        "artifact": "check-2-2.txt",
                    },
                ],
            },
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt", "tmp/run/review-final.txt"],
            "last_messages": ["tmp/run/remediation-2-last-message.txt"],
            "checks": ["tmp/run/check-2-1.txt", "tmp/run/check-2-2.txt"],
            "summary": "tmp/run/summary.json",
        },
        "base": "main",
        "max_iterations": 2,
        "resume_config": {
            "base": "main",
            "max_iterations": 2,
            "check_commands": ["./.venv/bin/ruff check .", "./.venv/bin/pytest -q"],
            "timeout_seconds": 0,
            "review_model": "gpt-5.5",
            "review_reasoning_effort": "low",
            "remediation_model": "gpt-5.4-mini",
            "remediation_reasoning_effort": "medium",
            "commit_message_model": "spark",
            "commit_message_harness": "codex",
            "commit_reasoning_effort": "minimal",
            "triage_enabled": True,
            "triage_contract": "v2",
            "triage_model": "gpt-5.5",
            "triage_harness": "codex",
            "triage_reasoning_effort": "low",
            "triage_timeout_seconds": 0,
            "routing_enabled": True,
            "routing_strict": False,
            "allow_model_escalation": False,
            "commit_after_remediation": True,
            "commit_on_hook_failure": "remediate",
        },
        "phase_config": {
            "review": {
                "harness": "codex",
                "model": "gpt-5.5",
                "reasoning_effort": "low",
                "timeout_seconds": 0,
                "source": "cli",
                "sources": {"model": "cli", "reasoning_effort": "cli"},
            },
            "triage": {
                "enabled": True,
                "contract": "v2",
                "harness": "codex",
                "model": "gpt-5.5",
                "reasoning_effort": "low",
                "timeout_seconds": 0,
                "source": "cli",
                "sources": {
                    "enabled": "cli",
                    "contract": "cli",
                    "model": "cli",
                    "harness": "cli",
                    "reasoning_effort": "cli",
                    "timeout_seconds": "cli",
                    "routing_enabled": "cli",
                    "routing_strict": "cli",
                    "allow_model_escalation": "cli",
                },
            },
            "remediation": {
                "harness": "codex",
                "model": "gpt-5.4-mini",
                "reasoning_effort": "medium",
                "source": "cli",
                "sources": {"model": "cli", "reasoning_effort": "cli"},
            },
            "commit_message": {
                "enabled": True,
                "harness": "codex",
                "model": "spark",
                "reasoning_effort": "minimal",
                "source": "cli",
                "sources": {"harness": "cli", "model": "cli", "reasoning_effort": "cli"},
            },
        },
        "latest_review_excerpt": "Full review comments:\n\n- [P2] Fix summary counts",
    }

    text = format_terminal_summary(summary)

    assert "Review-remediation loop: findings (max_iterations_reached)" in text
    assert "Phase config:" in text
    assert "Latest review: tmp/run/review-final.txt" in text
    assert (
        "Continue command: ./.venv/bin/revrem --base main --max-iterations 2 "
        "--check './.venv/bin/ruff check .' --check './.venv/bin/pytest -q' "
        "--timeout-seconds 0 --review-model gpt-5.5 --review-reasoning-effort low "
        "--remediation-model gpt-5.4-mini --remediation-reasoning-effort medium "
        "--commit-message-model spark --commit-message-harness codex "
        "--commit-reasoning-effort minimal --triage --triage-contract v2 "
        "--triage-model gpt-5.5 --triage-harness codex --triage-reasoning-effort low "
        "--triage-timeout-seconds 0 --routing --no-routing-strict "
        "--no-allow-model-escalation --commit-after-remediation --initial-review-file "
        "tmp/run/review-final.txt --commit-on-hook-failure remediate"
    ) in text
    assert "Latest remediation summary: tmp/run/remediation-2-last-message.txt" in text
    assert "Latest check status:" in text
    assert "passed: ./.venv/bin/ruff check . (tmp/run/check-2-1.txt)" in text
    assert "failed: ./.venv/bin/pytest -q (tmp/run/check-2-2.txt)" in text
    assert "- [P2] Fix summary counts" in text
    assert "source=cli" in text


def test_terminal_summary_falls_back_to_accurate_check_artifact_label():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "iterations": [{"iteration": 1, "review_status": "findings", "check_failures": 0}],
            "artifact_paths": {
                "checks": ["tmp/run/check-1-1.txt", "tmp/run/check-1-2.txt"],
                "summary": "tmp/run/summary.json",
            },
        }
    )

    assert "Latest check output artifacts:" in text


def test_terminal_summary_parse_miss_lists_all_check_artifacts():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "iterations": [{"iteration": 1, "review_status": "findings", "check_failures": 0}],
            "artifact_paths": {
                "checks": ["tmp/run/ruff.txt", "tmp/run/mypy.txt", "tmp/run/pytest.txt"],
            },
        }
    )

    assert "tmp/run/ruff.txt" in text
    assert "tmp/run/mypy.txt" in text
    assert "tmp/run/pytest.txt" in text


def test_terminal_summary_omits_latest_review_excerpt_when_clear():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "iterations": [
            {"iteration": 1, "review_status": "clear", "check_failures": None},
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt"],
            "summary": "tmp/run/summary.json",
        },
        "latest_review_excerpt": "I did not find any discrete, actionable bugs.",
    }

    text = format_terminal_summary(summary)

    assert "Review-remediation loop: clear (review_clear)" in text
    assert "Latest review: tmp/run/review-1.txt" in text
    assert "Latest actionable review output:" not in text
    assert "discrete, actionable bugs" not in text


def test_terminal_summary_prefers_commit_output_artifact():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "iterations": [
            {"iteration": 1, "review_status": "findings", "check_failures": 0, "commit_status": "committed"},
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt"],
            "commits": [
                "tmp/run/commit-1-add.txt",
                "tmp/run/commit-1-message-draft.txt",
                "tmp/run/commit-1.txt",
                "tmp/run/commit-1-message.txt",
            ],
            "summary": "tmp/run/summary.json",
        },
    }

    text = format_terminal_summary(summary)

    assert "1: review=findings, check failures: 0, commit=committed" in text
    assert "Latest commit artifact: tmp/run/commit-1.txt" in text


def test_terminal_summary_finds_commit_output_artifact_with_windows_separators():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "iterations": [],
        "artifact_paths": {
            "commits": [
                r"C:\tmp\run\commit-1-add.txt",
                r"C:\tmp\run\commit-1.txt",
                r"C:\tmp\run\commit-1-message.txt",
            ],
            "summary": r"C:\tmp\run\summary.json",
        },
    }

    text = format_terminal_summary(summary)

    assert r"Latest commit artifact: C:\tmp\run\commit-1.txt" in text


def test_summary_records_unknown_review_warning_and_bug_report(tmp_path):
    review_outputs = iter(
        [
            "This review output is ambiguous.\n",
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
        debug_status_detection=True,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
    text = format_terminal_summary(summary)
    report_path = tmp_path / "artifacts" / "unexpected-behavior-report.txt"

    assert summary["final_status"] == "clear"
    assert summary["unexpected_behaviors"] == [
        {
            "kind": "unknown_review_status",
            "iteration": 1,
            "review_path": str(tmp_path / "artifacts" / "review-1.txt"),
            "status_diagnostics_path": str(tmp_path / "artifacts" / "review-1-status.json"),
        }
    ]
    assert summary["bug_report_path"] == str(report_path)
    assert report_path.is_file()
    assert "iteration 1" in report_path.read_text(encoding="utf-8")
    assert "WARNING: unexpected loop behavior detected." in text
    assert f"Bug report details: {report_path}" in text


def test_unknown_final_review_is_recorded_in_diagnostics(tmp_path):
    review_outputs = iter(
        [
            "Needs work.\nREVIEW_STATUS: findings\n",
            "This final review is ambiguous.\n",
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
        debug_status_detection=True,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
    report_path = tmp_path / "artifacts" / "unexpected-behavior-report.txt"
    final_status_path = tmp_path / "artifacts" / "review-final-status.json"

    assert summary["final_status"] == "unknown"
    assert summary["unexpected_behaviors"] == [
        {
            "kind": "unknown_review_status",
            "iteration": "final",
            "review_path": str(tmp_path / "artifacts" / "review-final.txt"),
            "status_diagnostics_path": str(final_status_path),
        }
    ]
    assert summary["bug_report_path"] == str(report_path)
    assert report_path.is_file()
    assert final_status_path.is_file()
