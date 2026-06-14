from __future__ import annotations

import json
from pathlib import Path

import tests.support.application_runner as runner_mod
from code_review_loop import artifacts, reporting
from code_review_loop.cli.main import _redacted_argv
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.invocation import invocation_payload
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
    assert _redacted_argv(
        [
            "--api-token",
            "ghp_abcdefghijklmnopqrstuvwxyz123456",  # pragma: allowlist secret
            "--path=/home/example-user/project",
            "--opaque=0123456789abcdef0123456789abcdef",  # pragma: allowlist secret
        ]
    ) == (
        "--api-token",
        "[REDACTED:github-token]",
        "--path=[REDACTED:home]/project",
        "--opaque=[REDACTED:generic-token]",
    )


def test_invocation_payload_preserves_argv_and_redacts_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/home/example-user")

    payload = invocation_payload(
        executable="./.venv/bin/revrem",
        argv=[
            "--profile",
            "dogfood",
            "--triage-prompt",
            "secret prompt",
            "--opaque=0123456789abcdef0123456789abcdef",  # pragma: allowlist secret
        ],
        cwd=Path("/home/example-user/project"),
        command_line=("revrem", "--profile", "dogfood"),
        environ={
            "OTHER_TOOL": "ignored",
            "REVREM_API_KEY": "placeholder_revrem_api_key",  # pragma: allowlist secret
            "REVREM_FAKE_HARNESS_FIXTURE_DIR": "/home/example-user/fixtures",
            "REVREM_LIVE_KILO": "1",
        },
    )

    assert payload["argv"] == [
        "./.venv/bin/revrem",
        "--profile",
        "dogfood",
        "--triage-prompt",
        "<redacted>",
        "--opaque=[REDACTED:generic-token]",
    ]
    assert payload["cwd"] == "[REDACTED:home]/project"
    assert payload["command_line"] == ["revrem", "--profile", "dogfood"]
    assert payload["environment"] == {
        "REVREM_API_KEY": "[REDACTED:env-value]",
        "REVREM_FAKE_HARNESS_FIXTURE_DIR": "[REDACTED:home]/fixtures",
        "REVREM_LIVE_KILO": "1",
    }


def test_summary_writes_invocation_artifact_and_path(tmp_path):
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix init\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    invocation = {
        "schema_version": "1.0",
        "argv": ["./.venv/bin/revrem", "--base", "main"],
        "command_line": ["revrem", "--base", "main"],
        "cwd": str(tmp_path),
        "environment": {"REVREM_LIVE_KILO": "1"},
    }
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        command_line=("revrem", "--base", "main"),
        invocation=invocation,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
    invocation_path = tmp_path / "artifacts" / "invocation.json"
    artifact_payload = json.loads(invocation_path.read_text(encoding="utf-8"))

    assert artifact_payload == invocation
    assert summary["invocation"] == invocation
    assert summary["artifact_paths"]["invocation"] == str(invocation_path)


def test_summary_collects_commit_message_fallback_artifacts(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifacts.write_json_artifact(
        artifact_dir,
        "commit-2-message-fallback.json",
        {
            "iteration": 2,
            "reason": "model_drafting_failed",
            "subject": "fix(core): x (RevRem)",
        },
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


def test_summary_collects_commit_message_side_effect_artifacts(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifacts.write_json_artifact(
        artifact_dir,
        "commit-2-message-side-effects.json",
        {
            "schema_version": "1.0",
            "iteration": 2,
            "kind": "self_commit_adopted",
            "severity": "warning",
            "warning": "commit-message harness mutated repository state",
        },
    )
    summary: dict[str, object] = {}

    reporting.add_artifact_paths(summary, LoopConfig(artifact_dir=artifact_dir))

    assert summary["commit_message_side_effects"][0] == {
        "schema_version": "1.0",
        "iteration": 2,
        "kind": "self_commit_adopted",
        "severity": "warning",
        "warning": "commit-message harness mutated repository state",
        "artifact": str(artifact_dir / "commit-2-message-side-effects.json"),
    }


def test_summary_collects_phase_diagnostics_from_artifacts(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifacts.write_json_artifact(
        artifact_dir,
        "diagnostics-review-final-observation.json",
        {
            "phase": "review",
            "iteration": "final",
            "warnings": [
                {
                    "kind": "provider_config_mismatch",
                    "message": "Provider observed reasoning_effort='xhigh'.",
                }
            ],
        },
    )
    artifacts.write_json_artifact(
        artifact_dir,
        "diagnostics-review-final-failure.json",
        {
            "phase": "review",
            "iteration": "final",
            "failure": {"reason": "provider_timeout"},
            "redirected_retry_command": (
                "codex --model gpt-5.5 review -c 'model_reasoning_effort=\"low\"' "
                "> /tmp/revrem-review.txt 2>&1"
            ),
        },
    )
    summary: dict[str, object] = {}

    reporting.add_phase_diagnostics(summary, artifact_dir)

    assert summary["phase_observations"][0]["diagnostic_artifact"] == str(
        artifact_dir / "diagnostics-review-final-observation.json"
    )
    assert summary["phase_failures"][0]["diagnostic_artifact"] == str(
        artifact_dir / "diagnostics-review-final-failure.json"
    )


def test_terminal_summary_surfaces_final_review_failure_after_checks():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "error",
            "stopped_reason": "review_failed",
            "error": "codex review failed for review-final: provider subprocess timed out",
            "iterations": [
                {
                    "iteration": 1,
                    "review_status": "findings",
                    "check_failures": 0,
                    "checks": [
                        {"command": "ruff check .", "status": "passed"},
                        {"command": "pytest -q", "status": "passed"},
                    ],
                },
                {"iteration": "final", "review_failed": True},
            ],
            "phase_failures": [
                {
                    "phase": "review",
                    "iteration": "final",
                    "diagnostic_artifact": "tmp/run/diagnostics-review-final-failure.json",
                    "redirected_retry_command": (
                        "codex --model gpt-5.5 review -c "
                        "'model_reasoning_effort=\"low\"' > /tmp/revrem-review.txt 2>&1"
                    ),
                }
            ],
            "phase_observations": [
                {
                    "warnings": [
                        {
                            "kind": "provider_config_mismatch",
                            "message": (
                                "Provider observed reasoning_effort='xhigh' "
                                "but RevRem requested 'low'."
                            ),
                        }
                    ]
                }
            ],
        }
    )

    assert "Final review failed after remediation and checks passed." in text
    assert "Failure diagnostics: tmp/run/diagnostics-review-final-failure.json" in text
    assert "Retry final review: codex --model gpt-5.5 review" in text
    assert "WARNING: provider observations need attention." in text
    assert "Provider observed reasoning_effort='xhigh'" in text


def test_terminal_summary_keeps_raw_provider_finding_context_quiet():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [{"iteration": 1, "review_status": "clear"}],
            "phase_observations": [
                {
                    "phase": "review",
                    "iteration": "1",
                    "provider": "codex",
                    "banner_detected": False,
                    "observed": {},
                    "raw_provider_finding_count": 1,
                    "warnings": [],
                }
            ],
        }
    )

    assert "WARNING: provider observations need attention." not in text


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
                "sources": {
                    "harness": "cli",
                    "model": "cli",
                    "reasoning_effort": "cli",
                },
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


def test_terminal_summary_resume_command_preserves_forced_route():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "artifact_paths": {"reviews": ["tmp/run/review-final.txt"]},
            "base": "main",
            "max_iterations": 1,
            "resume_config": {
                "base": "main",
                "max_iterations": 1,
                "routing_default_route": "gemini-pro",
            },
            "phase_config": {
                "triage": {
                    "sources": {"routing_default_route": "cli"},
                },
            },
        }
    )

    assert "--route gemini-pro" in text


def test_terminal_summary_marks_unsupported_reasoning_effort_as_na():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "phase_config": {
                "review": {
                    "harness": "opencode",
                    "model": "opencode/minimax-m3-free",
                    "reasoning_effort": "low",
                    "reasoning_effort_supported": False,
                    "provider_reasoning_effort": None,
                    "timeout_seconds": 0,
                    "source": "mixed",
                    "sources": {"model": "cli", "timeout_seconds": "profile:dogfood"},
                }
            },
        }
    )

    assert (
        "review(opencode, opencode/minimax-m3-free, effort=n/a, timeout=0, source=profile+cli)"
    ) in text


def test_terminal_summary_resume_command_preserves_external_review_overrides():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "artifact_paths": {"reviews": ["tmp/run/review-final.txt"]},
            "base": "main",
            "max_iterations": 1,
            "resume_config": {
                "base": "main",
                "max_iterations": 1,
                "external_review_input_chars": 600_000,
                "external_review_warning_seconds": 600,
                "external_review_truncation_policy": "fail",
            },
            "phase_config": {
                "runtime": {
                    "sources": {
                        "external_review_input_chars": "cli",
                        "external_review_warning_seconds": "cli",
                        "external_review_truncation_policy": "cli",
                    },
                },
            },
        }
    )

    assert "--external-review-input-chars 600000" in text
    assert "--external-review-warning-seconds 600" in text
    assert "--external-review-truncation-policy fail" in text


def test_terminal_summary_resume_command_preserves_non_default_harnesses():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "artifact_paths": {"reviews": ["tmp/run/review-final.txt"]},
            "base": "main",
            "max_iterations": 1,
            "resume_config": {
                "base": "main",
                "max_iterations": 1,
                "review_harness": "opencode",
                "remediation_harness": "kilo",
            },
            "phase_config": {
                "review": {"harness": "opencode", "source": "cli"},
                "remediation": {"harness": "kilo", "source": "cli"},
            },
        }
    )

    assert "--review-harness opencode" in text
    assert "--remediation-harness kilo" in text


def test_resume_config_payload_persists_routing_default_route_when_profile_v2_set(tmp_path):
    from code_review_loop.config import LoopConfig
    from code_review_loop.profiles import Profile, parse_triage
    from code_review_loop.resume import resume_config_payload

    triage_payload = {
        "enabled": True,
        "harness": "codex",
        "model": None,
        "reasoning_effort": None,
        "timeout_seconds": 60,
        "contract": "v2",
        "routes": {"gemini-pro": {"harness": "gemini", "model": "gemini-3.1-pro-preview"}},
        "routing": {
            "enabled": True,
            "strict_on_unavailable_route": True,
            "default_route": "gemini-pro",
            "allow_model_escalation": True,
        },
    }
    profile_v2 = Profile(name="test", triage=parse_triage(triage_payload, "test"), source="test")
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path,
        profile_v2=profile_v2,
    )

    payload = resume_config_payload(config)

    assert payload["routing_default_route"] == "gemini-pro"


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
                "checks": [
                    "tmp/run/ruff.txt",
                    "tmp/run/mypy.txt",
                    "tmp/run/pytest.txt",
                ],
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


def test_terminal_summary_labels_stale_review_validation_output():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "clear",
            "stopped_reason": "stale_review_already_resolved",
            "artifact_paths": {
                "reviews": ["tmp/run/review-initial.txt"],
                "summary": "tmp/run/summary.json",
            },
            "latest_review_excerpt": (
                "REVREM_STALE_REVIEW_STATUS: resolved\n"
                "The cited whitespace finding no longer applies."
            ),
        }
    )

    assert "Review-remediation loop: clear (stale_review_already_resolved)" in text
    assert "Stale review validation output:" in text
    assert "Latest actionable review output:" not in text
    assert "The cited whitespace finding no longer applies." in text


def test_terminal_summary_prefers_commit_output_artifact():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "iterations": [
            {
                "iteration": 1,
                "review_status": "findings",
                "check_failures": 0,
                "commit_status": "committed",
            },
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


def test_terminal_summary_warns_for_commit_message_side_effects():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "iterations": [
            {
                "iteration": 1,
                "review_status": "clear",
                "check_failures": 0,
                "commit_status": "committed",
            }
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt"],
            "summary": "tmp/run/summary.json",
        },
        "commit_message_side_effects": [
            {
                "kind": "self_commit_adopted",
                "severity": "warning",
            }
        ],
    }

    text = format_terminal_summary(summary)

    assert "WARNING: commit-message harness mutated repository state" in text
    assert "unsuitable for commit-message drafting" in text


def test_summary_collects_triage_diagnostics_from_artifacts(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifacts.write_json_artifact(
        artifact_dir,
        "diagnostics-1.json",
        {
            "schema_version": "1.0",
            "status": "ok",
            "issues": [
                {
                    "code": "revrem.triage.invalid_output",
                    "severity": "warn",
                    "message": "Triage output was invalid.",
                }
            ],
        },
    )
    artifacts.write_json_artifact(
        artifact_dir,
        "triage-2.json",
        {
            "schema_version": "2.0",
            "parsing_warnings": [
                "Moved misplaced finding definition_of_done entries into prompt requirements.",
                "Normalized needs_more_info missing fingerprint to review-comment:1 fallback.",
            ],
        },
    )
    summary: dict[str, object] = {}

    reporting.add_triage_diagnostics(summary, artifact_dir)

    assert summary["triage_diagnostics"] == [
        {
            "kind": "issue",
            "code": "revrem.triage.invalid_output",
            "severity": "warn",
            "message": "Triage output was invalid.",
            "artifact": str(artifact_dir / "diagnostics-1.json"),
        },
        {
            "kind": "parsing_warning",
            "code": "revrem.triage.parsing_warning",
            "severity": "warn",
            "message": (
                "Moved misplaced finding definition_of_done entries into prompt requirements."
            ),
            "artifact": str(artifact_dir / "triage-2.json"),
        },
        {
            "kind": "parsing_note",
            "code": "revrem.triage.fallback_fingerprint",
            "severity": "info",
            "message": "Normalized needs_more_info missing fingerprint to review-comment:1 fallback.",
            "artifact": str(artifact_dir / "triage-2.json"),
        },
    ]


def test_triage_parsing_warning_diagnostic_treats_review_comment_fallback_as_note():
    diagnostic = reporting.triage_parsing_warning_diagnostic(
        "Normalized needs_more_info missing fingerprint to review-comment:1 fallback."
    )

    assert diagnostic == {
        "kind": "parsing_note",
        "code": "revrem.triage.fallback_fingerprint",
        "severity": "info",
        "message": "Normalized needs_more_info missing fingerprint to review-comment:1 fallback.",
    }


def test_terminal_summary_surfaces_triage_diagnostics():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "iterations": [],
            "triage_diagnostics": [
                {
                    "code": "revrem.triage.parsing_warning",
                    "message": "Moved misplaced finding definition_of_done entries.",
                    "artifact": "tmp/run/triage-1.json",
                }
            ],
        }
    )

    assert "WARNING: triage diagnostics were recorded." in text
    assert "revrem.triage.parsing_warning" in text
    assert "tmp/run/triage-1.json" in text


def test_terminal_summary_reports_info_only_triage_diagnostics_as_notes():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
            "triage_diagnostics": [
                {
                    "code": "revrem.triage.fallback_fingerprint",
                    "severity": "info",
                    "message": "Review comment fell back to review-comment:1.",
                    "artifact": "tmp/run/triage-1.json",
                }
            ],
        }
    )

    assert "WARNING: triage diagnostics were recorded." not in text
    assert "Triage notes were recorded." in text
    assert "revrem.triage.fallback_fingerprint" in text
    assert "tmp/run/triage-1.json" in text


def test_terminal_summary_surfaces_check_retry_history():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "iterations": [
                {
                    "iteration": 1,
                    "review_status": "findings",
                    "check_failures": 0,
                    "check_attempts": [
                        {
                            "retry": 0,
                            "check_failures": 1,
                            "checks": [
                                {
                                    "command": "git status -z --porcelain=v1 --untracked-files=all",
                                    "status": "failed",
                                }
                            ],
                        },
                        {
                            "retry": 1,
                            "check_failures": 0,
                            "checks": [
                                {
                                    "command": "git status -z --porcelain=v1 --untracked-files=all",
                                    "status": "passed",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )

    assert "check retry: first failed 1, latest failed 0" in text
    assert "first failed: git status -z --porcelain=v1 --untracked-files=all" in text


def test_terminal_summary_surfaces_timing_warning():
    text = format_terminal_summary(
        {
            "artifact_dir": "tmp/run",
            "final_status": "findings",
            "stopped_reason": "max_iterations_reached",
            "iterations": [],
            "timing_warnings": [
                {
                    "message": (
                        "Wall-clock duration substantially exceeds active elapsed time; "
                        "the host may have slept, suspended, or delayed process scheduling."
                    )
                }
            ],
        }
    )

    assert "Wall-clock duration substantially exceeds active elapsed time" in text


def test_summary_records_terminal_unknown_review_warning_and_bug_report(tmp_path):
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

    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "review_unknown"
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
    assert "Review-remediation loop: unknown (review_unknown)" in text
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
