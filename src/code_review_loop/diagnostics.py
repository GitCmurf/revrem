"""Deterministic local diagnostics for RevRem setup checks."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_review_loop import fingerprints

DIAGNOSTICS_SCHEMA_VERSION = "1.0"
SEVERITY_ORDER = {"blocking": 0, "warn": 1, "ok": 2}


@dataclass(frozen=True)
class DiagnosticIssue:
    code: str
    severity: str
    message: str
    hint: str
    evidence: dict[str, Any] = field(default_factory=dict)
    fingerprint: str | None = None
    schema_version: str = DIAGNOSTICS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        fingerprint = self.fingerprint or diagnostic_fingerprint(self)
        return {
            "schema_version": self.schema_version,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "hint": self.hint,
            "evidence": self.evidence,
            "fingerprint": fingerprint,
        }


@dataclass(frozen=True)
class DoctorConfig:
    cwd: Path
    base: str = "main"
    artifact_dir: Path | None = None
    artifact_dir_is_default: bool = False
    codex_bin: str = "codex"
    check_commands: tuple[str, ...] = ()
    commit_after_remediation: bool = False


def run_doctor(config: DoctorConfig) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    git_root_result = _git(config.cwd, "rev-parse", "--show-toplevel")
    if git_root_result.returncode == 127:
        issues.append(
            DiagnosticIssue(
                code="revrem.preflight.git_not_found",
                severity="blocking",
                message="Git executable was not found on PATH.",
                hint="Install Git or make it available on PATH before running RevRem doctor.",
                evidence={"cwd": str(config.cwd), "error": git_root_result.stderr.strip()},
            )
        )
        git_root = None
    elif git_root_result.returncode != 0:
        issues.append(
            DiagnosticIssue(
                code="revrem.preflight.not_git_repo",
                severity="blocking",
                message="Current directory is not inside a Git repository.",
                hint="Run RevRem from a Git checkout.",
                evidence={"cwd": str(config.cwd)},
            )
        )
        git_root = None
    else:
        git_root = Path(git_root_result.stdout.strip())
        issues.extend(_git_issues(config, git_root))

    issues.extend(_artifact_dir_issues(config, git_root))
    issues.extend(_executable_issues(config))

    if not issues:
        issues.append(
            DiagnosticIssue(
                code="revrem.preflight.ok",
                severity="ok",
                message="RevRem preflight checks passed.",
                hint="Run revrem with the same base and checks to start the review loop.",
                evidence={"cwd": str(config.cwd), "base": config.base},
            )
        )
    return sorted(issues, key=lambda issue: (SEVERITY_ORDER[issue.severity], issue.code))


def has_blocking_issue(issues: list[DiagnosticIssue]) -> bool:
    return any(issue.severity == "blocking" for issue in issues)


def has_warning_issue(issues: list[DiagnosticIssue]) -> bool:
    return any(issue.severity == "warn" for issue in issues)


def diagnostic_fingerprint(issue: DiagnosticIssue) -> str:
    """Return a stable F4 fingerprint for a diagnostic issue."""
    return fingerprints.finding_fingerprint(
        fingerprints.FindingFingerprintInput(
            rule_id=issue.code,
            path=".",
            message=issue.message,
            severity=_diagnostic_severity_bucket(issue.severity),
        )
    )


def _diagnostic_severity_bucket(severity: str) -> str:
    if severity == "blocking":
        return "high"
    if severity == "warn":
        return "medium"
    return "info"


def doctor_payload(issues: list[DiagnosticIssue]) -> dict[str, Any]:
    return {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "status": "blocking" if has_blocking_issue(issues) else "ok",
        "issues": [issue.to_dict() for issue in issues],
    }


def doctor_json(issues: list[DiagnosticIssue]) -> str:
    return json.dumps(doctor_payload(issues), indent=2, sort_keys=True) + "\n"


def doctor_text(issues: list[DiagnosticIssue]) -> str:
    lines: list[str] = []
    for issue in issues:
        label = issue.severity.upper()
        lines.append(f"{label}: {issue.code}: {issue.message}")
        if issue.hint:
            lines.append(f"  hint: {issue.hint}")
    return "\n".join(lines) + "\n"


def _git_issues(config: DoctorConfig, git_root: Path) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    base_result = _git(config.cwd, "rev-parse", "--verify", config.base)
    if base_result.returncode != 0:
        issues.append(
            DiagnosticIssue(
                code="revrem.preflight.invalid_base",
                severity="blocking",
                message=f"Base ref {config.base!r} does not resolve.",
                hint="Fetch the target branch or pass --base with an existing ref.",
                evidence={"base": config.base, "stderr": base_result.stderr.strip()},
            )
        )
        return issues

    merge_base = _git(config.cwd, "merge-base", "HEAD", config.base)
    if merge_base.returncode != 0:
        issues.append(
            DiagnosticIssue(
                code="revrem.preflight.no_merge_base",
                severity="blocking",
                message=f"HEAD and base ref {config.base!r} do not share history.",
                hint="Use a base branch with shared history, or update the local base ref.",
                evidence={"base": config.base, "git_root": str(git_root)},
            )
        )

    if config.commit_after_remediation:
        status = _git(config.cwd, "status", "--porcelain")
        if status.returncode == 0 and status.stdout.strip():
            issues.append(
                DiagnosticIssue(
                    code="revrem.preflight.dirty_worktree_commit_mode",
                    severity="blocking",
                    message="Commit mode requires a clean worktree before the loop starts.",
                    hint="Commit, stash, or discard local changes before using --commit-after-remediation.",
                    evidence={"git_root": str(git_root)},
                )
            )
    return issues


def _artifact_dir_issues(config: DoctorConfig, git_root: Path | None) -> list[DiagnosticIssue]:
    if config.artifact_dir is None:
        return []
    try:
        target = config.artifact_dir if config.artifact_dir.is_absolute() else config.cwd / config.artifact_dir
        if config.artifact_dir_is_default:
            _validate_default_artifact_dir(target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".revrem-doctor-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
    except OSError as exc:
        return [
            DiagnosticIssue(
                code="revrem.preflight.artifact_dir_not_writable",
                severity="blocking",
                message="Artifact directory is not writable.",
                hint="Choose a writable --artifact-dir path.",
                evidence={
                    "artifact_dir": str(config.artifact_dir),
                    "resolved_artifact_dir": str(target),
                    "error": str(exc),
                },
            )
        ]
    if config.commit_after_remediation and git_root is not None:
        try:
            artifact_rel = target.resolve().relative_to(git_root)
        except ValueError:
            return []
        if artifact_rel == Path("."):
            return [
                DiagnosticIssue(
                    code="revrem.preflight.artifact_dir_resolves_to_repo_root",
                    severity="blocking",
                    message="Commit mode refuses to auto-commit when --artifact-dir resolves to the repository root.",
                    hint="Choose a subdirectory for generated artifacts.",
                    evidence={
                        "artifact_dir": str(config.artifact_dir),
                        "resolved_artifact_dir": str(target.resolve()),
                        "git_root": str(git_root),
                    },
                )
            ]
    return []


def _validate_default_artifact_dir(target: Path) -> None:
    conflict = _first_conflicting_path(target)
    if conflict is not None:
        raise NotADirectoryError(conflict)
    probe_parent = _nearest_existing_directory(target.parent)
    probe = probe_parent / ".revrem-doctor-write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _first_conflicting_path(target: Path) -> Path | None:
    current = target
    while True:
        if current.exists() and not current.is_dir():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _nearest_existing_directory(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    if not current.is_dir():
        raise NotADirectoryError(current)
    return current


def _executable_issues(config: DoctorConfig) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    if shutil.which(config.codex_bin) is None:
        issues.append(
            DiagnosticIssue(
                code="revrem.preflight.codex_not_found",
                severity="blocking",
                message=f"Codex executable {config.codex_bin!r} was not found on PATH.",
                hint="Install Codex or pass --codex-bin with the executable path.",
                evidence={"codex_bin": config.codex_bin},
            )
        )
    for command in config.check_commands:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            issues.append(
                DiagnosticIssue(
                    code="revrem.preflight.check_command_unparseable",
                    severity="blocking",
                    message="Check command could not be parsed.",
                    hint="Use shell-like quoting that can be parsed by shlex, or remove the check.",
                    evidence={"check": command, "error": str(exc)},
                )
            )
            continue
        executable = parts[0] if parts else ""
        if not executable or shutil.which(executable) is None:
            issues.append(
                DiagnosticIssue(
                    code="revrem.preflight.check_command_not_found",
                    severity="blocking",
                    message=f"Check command executable {executable!r} was not found on PATH.",
                    hint="Install the tool or remove the check from the profile/CLI.",
                    evidence={"check": command, "executable": executable},
                )
            )
    return issues


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            127,
            stdout="",
            stderr=str(exc),
        )
