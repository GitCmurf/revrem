"""TOML profile loading and resolution for RevRem."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from code_review_loop import run_history
from code_review_loop._compat_tomli_w import dumps as toml_dumps
from code_review_loop.harnesses import (
    HARNESS_REGISTRY,
    require_implemented_harness,
    validate_harness_name,
)

USER_CONFIG_RELATIVE = Path(".config") / "revrem" / "profiles.toml"
PROJECT_CONFIG_NAME = ".revrem.toml"
TOML_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
EXEC_SANDBOX_CHOICES = ("read-only", "workspace-write", "danger-full-access")
EXEC_COLOR_CHOICES = ("always", "never", "auto")
REASONING_EFFORT_CHOICES = ("minimal", "low", "medium", "high")
PROFILE_KEYS = (
    "description",
    "pipeline",
    "review",
    "triage",
    "remediation",
    "commit",
    "output",
    "runtime",
    "budgets",
    "suppressions",
)
PIPELINE_KEYS = ("base", "max_iterations", "final_review", "checks")
PHASE_KEYS = ("harness", "model", "reasoning_effort", "timeout_seconds")
TRIAGE_ON_INVALID_CHOICES = ("continue", "stop")
COMMIT_ON_HOOK_FAILURE_CHOICES = ("remediate", "stop", "no-verify")
TRIAGE_KEYS = (
    "enabled",
    "harness",
    "model",
    "reasoning_effort",
    "timeout_seconds",
    "prompt",
    "on_invalid",
)
COMMIT_KEYS = (
    "enabled",
    "harness",
    "message_model",
    "message_prompt",
    "on_hook_failure",
)
OUTPUT_KEYS = (
    "summary_format",
    "debug_status_detection",
    "progress_style",
    "quiet_progress",
    "terminal_title",
    "artifact_dir",
)
RUNTIME_KEYS = (
    "codex_bin",
    "exec_sandbox",
    "exec_color",
    "exec_json",
    "output_last_message",
    "full_auto",
    "max_remediation_input_chars",
    "terminal_excerpt_chars",
)
BUDGET_KEYS = ("max_wall_seconds", "max_tokens", "max_usd", "soft_warn_fraction")
SUPPRESSION_SCOPE_CHOICES = ("repo", "user")
SUPPRESSIONS_KEYS = ("scope",)
TOP_LEVEL_KEYS = ("defaults", "profiles")


@dataclass(frozen=True)
class PhaseConfig:
    harness: str = "codex"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class TriageConfig:
    enabled: bool = False
    harness: str = "codex"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    prompt: str | None = None
    on_invalid: str = "continue"


@dataclass(frozen=True)
class PipelineConfig:
    base: str = "main"
    max_iterations: int = 2
    final_review: bool = True
    checks: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommitConfig:
    enabled: bool = False
    harness: str = "codex"
    message_model: str | None = "gpt-5.3-codex-spark"
    message_prompt: str | None = None
    on_hook_failure: str = "remediate"


@dataclass(frozen=True)
class OutputConfig:
    summary_format: str = "text"
    debug_status_detection: bool = False
    progress_style: str = "compact"
    quiet_progress: bool = False
    terminal_title: bool = False
    artifact_dir: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    codex_bin: str = "codex"
    exec_sandbox: str = "workspace-write"
    exec_color: str = "never"
    exec_json: bool = False
    output_last_message: bool = True
    full_auto: bool = True
    max_remediation_input_chars: int = 200_000
    terminal_excerpt_chars: int = 4_000


@dataclass(frozen=True)
class BudgetConfig:
    max_wall_seconds: float | None = None
    max_tokens: int | None = None
    max_usd: Decimal | None = None
    soft_warn_fraction: float = 0.8


@dataclass(frozen=True)
class SuppressionsConfig:
    scope: str = "repo"


@dataclass(frozen=True)
class Profile:
    name: str
    description: str = ""
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    review: PhaseConfig = field(default_factory=PhaseConfig)
    triage: TriageConfig = field(default_factory=TriageConfig)
    remediation: PhaseConfig = field(default_factory=PhaseConfig)
    commit: CommitConfig = field(default_factory=CommitConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    suppressions: SuppressionsConfig = field(default_factory=SuppressionsConfig)
    source: str | None = None


@dataclass(frozen=True)
class ProfileFile:
    path: Path
    profiles: dict[str, Profile]
    raw_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    defaults: Profile | None = None
    raw_defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileListItem:
    name: str
    description: str
    source: str | None
    last_used_at: str | None


def user_config_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / USER_CONFIG_RELATIVE


def project_config_path(cwd: Path) -> Path:
    return _repo_root(cwd) / PROJECT_CONFIG_NAME


def _repo_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def load_profile_file(path: Path) -> ProfileFile:
    if not path.is_file():
        return ProfileFile(path=path, profiles={})
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"profile file is not a TOML table: {path}")
    _reject_unknown_keys(raw, TOP_LEVEL_KEYS, f"profile file {path}")
    defaults = None
    defaults_raw: dict[str, Any] = {}
    if "defaults" in raw:
        defaults_raw = _table(raw["defaults"], f"{path}:defaults")
        defaults = parse_profile("<defaults>", defaults_raw, source=str(path))
    profiles_raw = raw.get("profiles", {})
    profiles_table = _table(profiles_raw, f"{path}:profiles")
    raw_profiles = {
        name: _table(value, f"{path}:profiles.{name}")
        for name, value in profiles_table.items()
    }
    profiles = {
        name: parse_profile(name, value, source=str(path))
        for name, value in raw_profiles.items()
    }
    return ProfileFile(
        path=path,
        profiles=profiles,
        raw_profiles=raw_profiles,
        defaults=defaults,
        raw_defaults=defaults_raw,
    )


def parse_profile(name: str, raw: dict[str, Any], *, source: str | None = None) -> Profile:
    _reject_unknown_keys(raw, PROFILE_KEYS, f"{name}")
    description = _optional_str(raw.get("description"), f"{name}.description") or ""
    pipeline = parse_pipeline(_table(raw.get("pipeline", {}), f"{name}.pipeline"))
    review = parse_phase(_table(raw.get("review", {}), f"{name}.review"), f"{name}.review")
    triage = parse_triage(_table(raw.get("triage", {}), f"{name}.triage"), f"{name}.triage")
    remediation = parse_phase(
        _table(raw.get("remediation", {}), f"{name}.remediation"),
        f"{name}.remediation",
    )
    output = parse_output(_table(raw.get("output", {}), f"{name}.output"))
    commit = parse_commit(_table(raw.get("commit", {}), f"{name}.commit"))
    runtime = parse_runtime(_table(raw.get("runtime", {}), f"{name}.runtime"))
    budgets = parse_budgets(_table(raw.get("budgets", {}), f"{name}.budgets"))
    suppressions = parse_suppressions(
        _table(raw.get("suppressions", {}), f"{name}.suppressions")
    )
    profile = Profile(
        name=name,
        description=description,
        pipeline=pipeline,
        review=review,
        triage=triage,
        remediation=remediation,
        commit=commit,
        output=output,
        runtime=runtime,
        budgets=budgets,
        suppressions=suppressions,
        source=source,
    )
    validate_profile(profile, require_implemented=False)
    return profile


def parse_pipeline(raw: dict[str, Any]) -> PipelineConfig:
    _reject_unknown_keys(raw, PIPELINE_KEYS, "pipeline")
    checks = raw.get("checks", ())
    if checks is None:
        checks = ()
    if not isinstance(checks, list | tuple) or not all(isinstance(item, str) for item in checks):
        raise ValueError("pipeline.checks must be a list of strings")
    return PipelineConfig(
        base=_str(raw.get("base", "main"), "pipeline.base"),
        max_iterations=_int(raw.get("max_iterations", 2), "pipeline.max_iterations"),
        final_review=_bool(raw.get("final_review", True), "pipeline.final_review"),
        checks=tuple(checks),
    )


def parse_phase(raw: dict[str, Any], field: str) -> PhaseConfig:
    _reject_unknown_keys(raw, PHASE_KEYS, field)
    harness = _str(raw.get("harness", "codex"), f"{field}.harness")
    validate_harness_name(harness, field=f"{field}.harness")
    reasoning_effort = _optional_str(raw.get("reasoning_effort"), f"{field}.reasoning_effort")
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORT_CHOICES:
        raise ValueError(
            f"{field}.reasoning_effort must be one of {', '.join(REASONING_EFFORT_CHOICES)}"
        )
    return PhaseConfig(
        harness=harness,
        model=_optional_str(raw.get("model"), f"{field}.model"),
        reasoning_effort=reasoning_effort,
        timeout_seconds=_optional_float(raw.get("timeout_seconds"), f"{field}.timeout_seconds"),
    )


def parse_triage(raw: dict[str, Any], field: str) -> TriageConfig:
    _reject_unknown_keys(raw, TRIAGE_KEYS, field)
    harness = _str(raw.get("harness", "codex"), f"{field}.harness")
    validate_harness_name(harness, field=f"{field}.harness")
    reasoning_effort = _optional_str(raw.get("reasoning_effort"), f"{field}.reasoning_effort")
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORT_CHOICES:
        raise ValueError(
            f"{field}.reasoning_effort must be one of {', '.join(REASONING_EFFORT_CHOICES)}"
        )
    on_invalid = _str(raw.get("on_invalid", "continue"), f"{field}.on_invalid")
    if on_invalid not in TRIAGE_ON_INVALID_CHOICES:
        raise ValueError(
            f"{field}.on_invalid must be one of {', '.join(TRIAGE_ON_INVALID_CHOICES)}"
        )
    return TriageConfig(
        enabled=_bool(raw.get("enabled", False), f"{field}.enabled"),
        harness=harness,
        model=_optional_str(raw.get("model"), f"{field}.model"),
        reasoning_effort=reasoning_effort,
        timeout_seconds=_optional_float(raw.get("timeout_seconds"), f"{field}.timeout_seconds"),
        prompt=_optional_str(raw.get("prompt"), f"{field}.prompt"),
        on_invalid=on_invalid,
    )


def parse_commit(raw: dict[str, Any]) -> CommitConfig:
    _reject_unknown_keys(raw, COMMIT_KEYS, "commit")
    harness = _str(raw.get("harness", "codex"), "commit.harness")
    validate_harness_name(harness, field="commit.harness")
    on_hook_failure = _str(raw.get("on_hook_failure", "remediate"), "commit.on_hook_failure")
    if on_hook_failure not in COMMIT_ON_HOOK_FAILURE_CHOICES:
        raise ValueError(
            "commit.on_hook_failure must be one of "
            f"{', '.join(COMMIT_ON_HOOK_FAILURE_CHOICES)}"
        )
    return CommitConfig(
        enabled=_bool(raw.get("enabled", False), "commit.enabled"),
        harness=harness,
        message_model=_optional_str(raw.get("message_model"), "commit.message_model")
        or "gpt-5.3-codex-spark",
        message_prompt=_optional_str(raw.get("message_prompt"), "commit.message_prompt"),
        on_hook_failure=on_hook_failure,
    )


def parse_output(raw: dict[str, Any]) -> OutputConfig:
    _reject_unknown_keys(raw, OUTPUT_KEYS, "output")
    summary_format = _str(raw.get("summary_format", "text"), "output.summary_format")
    if summary_format not in {"text", "json", "both"}:
        raise ValueError("output.summary_format must be text, json, or both")
    progress_style = _str(raw.get("progress_style", "compact"), "output.progress_style")
    if progress_style not in {"compact", "verbose", "rich"}:
        raise ValueError("output.progress_style must be compact, verbose, or rich")
    return OutputConfig(
        summary_format=summary_format,
        debug_status_detection=_bool(
            raw.get("debug_status_detection", False),
            "output.debug_status_detection",
        ),
        progress_style=progress_style,
        quiet_progress=_bool(raw.get("quiet_progress", False), "output.quiet_progress"),
        terminal_title=_bool(raw.get("terminal_title", False), "output.terminal_title"),
        artifact_dir=_optional_str(raw.get("artifact_dir"), "output.artifact_dir"),
    )


def parse_runtime(raw: dict[str, Any]) -> RuntimeConfig:
    _reject_unknown_keys(raw, RUNTIME_KEYS, "runtime")
    return RuntimeConfig(
        codex_bin=_str(raw.get("codex_bin", "codex"), "runtime.codex_bin"),
        exec_sandbox=_str(raw.get("exec_sandbox", "workspace-write"), "runtime.exec_sandbox"),
        exec_color=_str(raw.get("exec_color", "never"), "runtime.exec_color"),
        exec_json=_bool(raw.get("exec_json", False), "runtime.exec_json"),
        output_last_message=_bool(
            raw.get("output_last_message", True),
            "runtime.output_last_message",
        ),
        full_auto=_bool(raw.get("full_auto", True), "runtime.full_auto"),
        max_remediation_input_chars=_int(
            raw.get("max_remediation_input_chars", 200_000),
            "runtime.max_remediation_input_chars",
        ),
        terminal_excerpt_chars=_int(
            raw.get("terminal_excerpt_chars", 4_000),
            "runtime.terminal_excerpt_chars",
        ),
    )


def parse_budgets(raw: dict[str, Any]) -> BudgetConfig:
    _reject_unknown_keys(raw, BUDGET_KEYS, "budgets")
    soft_warn_fraction = _float(raw.get("soft_warn_fraction", 0.8), "budgets.soft_warn_fraction")
    if not 0 < soft_warn_fraction <= 1:
        raise ValueError("budgets.soft_warn_fraction must be greater than 0 and no more than 1")
    max_tokens = _optional_int(raw.get("max_tokens"), "budgets.max_tokens")
    if max_tokens is not None and max_tokens < 0:
        raise ValueError("budgets.max_tokens must be 0 or greater")
    max_wall_seconds = _optional_float(raw.get("max_wall_seconds"), "budgets.max_wall_seconds")
    if max_wall_seconds is not None and max_wall_seconds < 0:
        raise ValueError("budgets.max_wall_seconds must be 0 or greater")
    max_usd = _optional_decimal(raw.get("max_usd"), "budgets.max_usd")
    if max_usd is not None and max_usd < 0:
        raise ValueError("budgets.max_usd must be 0 or greater")
    return BudgetConfig(
        max_wall_seconds=max_wall_seconds,
        max_tokens=max_tokens,
        max_usd=max_usd,
        soft_warn_fraction=soft_warn_fraction,
    )


def parse_suppressions(raw: dict[str, Any]) -> SuppressionsConfig:
    _reject_unknown_keys(raw, SUPPRESSIONS_KEYS, "suppressions")
    scope = _str(raw.get("scope", "repo"), "suppressions.scope")
    if scope not in SUPPRESSION_SCOPE_CHOICES:
        raise ValueError(
            "suppressions.scope must be one of: "
            f"{', '.join(SUPPRESSION_SCOPE_CHOICES)}"
        )
    return SuppressionsConfig(scope=scope)


def resolve_profile(
    name: str,
    *,
    cwd: Path,
    home: Path | None = None,
    require_implemented: bool = True,
) -> Profile:
    user_file, project_file = load_profile_files(cwd=cwd, home=home)
    return resolve_profile_from_files(
        name,
        user_file=user_file,
        project_file=project_file,
        require_implemented=require_implemented,
    )


def resolve_profiles(
    *,
    cwd: Path,
    home: Path | None = None,
    require_implemented: bool = True,
) -> list[Profile]:
    user_file, project_file = load_profile_files(cwd=cwd, home=home)
    names = sorted(set(user_file.profiles) | set(project_file.profiles))
    return [
        resolve_profile_from_files(
            name,
            user_file=user_file,
            project_file=project_file,
            require_implemented=require_implemented,
        )
        for name in names
    ]


def load_profile_files(*, cwd: Path, home: Path | None = None) -> tuple[ProfileFile, ProfileFile]:
    return load_profile_file(user_config_path(home)), load_profile_file(project_config_path(cwd))


def resolve_profile_from_files(
    name: str,
    *,
    user_file: ProfileFile,
    project_file: ProfileFile,
    require_implemented: bool = True,
) -> Profile:
    raw: dict[str, Any] = {}
    source = None
    found = False
    if user_file.defaults is not None:
        raw = _deep_merge(raw, user_file.raw_defaults)
        source = str(user_file.path)
    if name in user_file.profiles:
        raw = _deep_merge(raw, user_file.raw_profiles[name])
        source = str(user_file.path)
        found = True
    if project_file.defaults is not None:
        raw = _deep_merge(raw, project_file.raw_defaults)
        source = str(project_file.path)
    if name in project_file.profiles:
        raw = _deep_merge(raw, project_file.raw_profiles[name])
        source = str(project_file.path)
        found = True
    if not found:
        raise FileNotFoundError(f"profile not found: {name}")
    resolved = parse_profile(name, raw, source=source)
    validate_profile(resolved, require_implemented=require_implemented)
    return resolved


def resolve_defaults(
    *,
    cwd: Path,
    home: Path | None = None,
    require_implemented: bool = True,
) -> Profile:
    user_file = load_profile_file(user_config_path(home))
    project_file = load_profile_file(project_config_path(cwd))
    raw: dict[str, Any] = {}
    source = None
    if user_file.defaults is not None:
        raw = _deep_merge(raw, user_file.raw_defaults)
        source = str(user_file.path)
    if project_file.defaults is not None:
        raw = _deep_merge(raw, project_file.raw_defaults)
        source = str(project_file.path)
    defaults = parse_profile("<defaults>", raw, source=source)
    validate_profile(defaults, require_implemented=require_implemented)
    return defaults


def list_profiles(*, cwd: Path, home: Path | None = None) -> list[Profile]:
    files = load_profile_files(cwd=cwd, home=home)
    seen: dict[str, Profile] = {}
    for profile_file in files:
        for name, profile in profile_file.profiles.items():
            seen[name] = profile
    return [seen[name] for name in sorted(seen)]


def profile_list_items(
    *,
    cwd: Path,
    home: Path | None = None,
    history_path: Path | None = None,
) -> list[ProfileListItem]:
    last_used_at_by_profile = _profile_last_used_at_by_name(history_path)
    return [
        ProfileListItem(
            name=profile.name,
            description=profile.description,
            source=profile.source,
            last_used_at=last_used_at_by_profile.get(profile.name),
        )
        for profile in list_profiles(cwd=cwd, home=home)
    ]


def profile_list_item_to_dict(item: ProfileListItem) -> dict[str, Any]:
    return asdict(item)


def merge_profiles(name: str, *profiles: Profile) -> Profile:
    if not profiles:
        raise ValueError("merge_profiles requires at least one profile")
    result = replace(profiles[0], name=name)
    for profile in profiles[1:]:
        result = Profile(
            name=name,
            description=profile.description or result.description,
            pipeline=_merge_dataclass(result.pipeline, profile.pipeline),
            review=_merge_dataclass(result.review, profile.review),
            triage=_merge_dataclass(result.triage, profile.triage),
            remediation=_merge_dataclass(result.remediation, profile.remediation),
            commit=_merge_dataclass(result.commit, profile.commit),
            output=_merge_dataclass(result.output, profile.output),
            runtime=_merge_dataclass(result.runtime, profile.runtime),
            budgets=_merge_dataclass(result.budgets, profile.budgets),
            suppressions=_merge_dataclass(result.suppressions, profile.suppressions),
            source=profile.source or result.source,
        )
    return result


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return cast(dict[str, Any], _json_ready(asdict(profile)))


def profile_to_json(profile: Profile) -> str:
    return json.dumps(profile_to_dict(profile), indent=2, sort_keys=True) + "\n"


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _profile_last_used_at_by_name(history_path: Path | None = None) -> dict[str, str]:
    last_used_at_by_name: dict[str, str] = {}
    for record in run_history.read_history(history_path):
        profile_name = record.get("profile")
        if not isinstance(profile_name, str) or profile_name in last_used_at_by_name:
            continue
        timestamp = record.get("finished_at") or record.get("started_at")
        if isinstance(timestamp, str):
            last_used_at_by_name[profile_name] = timestamp
    return last_used_at_by_name


def profile_to_toml(profile: Profile, *, include_wrapper: bool = False) -> str:
    return _profile_to_toml_impl(
        profile,
        root=("profiles", profile.name) if include_wrapper else None,
        omit_builtin_defaults=False,
    )


def _profile_to_toml_dict(
    profile: Profile,
    *,
    omit_builtin_defaults: bool,
    omit_reference_defaults: bool = False,
    reference: Profile | None = None,
    raw_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if profile.description:
        result["description"] = profile.description
    for section_name in (
        "pipeline",
        "review",
        "triage",
        "remediation",
        "commit",
        "output",
        "runtime",
        "budgets",
        "suppressions",
    ):
        value = getattr(profile, section_name)
        defaults = type(value)()
        reference_value = getattr(reference, section_name) if reference is not None else None
        raw_section = raw_profile.get(section_name) if raw_profile is not None else None
        section_dict: dict[str, Any] = {}
        for key, item in asdict(value).items():
            if item is None:
                continue
            reference_item = getattr(reference_value, key) if reference_value is not None else None
            if omit_reference_defaults and reference_value is not None and item == reference_item:
                continue
            explicit = isinstance(raw_section, dict) and key in raw_section
            if omit_builtin_defaults and item == getattr(defaults, key) and not explicit:
                continue
            if isinstance(item, tuple):
                section_dict[key] = list(item)
            elif isinstance(item, Decimal):
                section_dict[key] = str(item)
            else:
                section_dict[key] = item
        if section_dict:
            result[section_name] = section_dict
    return result


def _profile_to_toml_impl(
    profile: Profile,
    *,
    root: tuple[str, ...] | None,
    omit_builtin_defaults: bool,
    omit_reference_defaults: bool = False,
    reference: Profile | None = None,
    raw_profile: dict[str, Any] | None = None,
) -> str:
    inner = _profile_to_toml_dict(
        profile,
        omit_builtin_defaults=omit_builtin_defaults,
        omit_reference_defaults=omit_reference_defaults,
        reference=reference,
        raw_profile=raw_profile,
    )
    if root is None:
        return toml_dumps(inner)
    return toml_dumps(_nest_dict(root, inner))


def write_user_profile(
    profile: Profile,
    *,
    home: Path | None = None,
    force: bool = False,
    raw_profile: dict[str, Any] | None = None,
) -> Path:
    path = user_config_path(home)
    return write_profile_to_path(path, profile, force=force, raw_profile=raw_profile)


def write_project_profile(
    profile: Profile,
    *,
    cwd: Path,
    force: bool = False,
    raw_profile: dict[str, Any] | None = None,
) -> Path:
    path = project_config_path(cwd)
    profile_file = load_profile_file(path)
    if profile.name in profile_file.profiles and not force:
        raise FileExistsError(f"profile already exists: {profile.name}")
    _write_profile_file(
        path,
        defaults=profile_file.defaults,
        raw_defaults=profile_file.raw_defaults if profile_file.defaults is not None else None,
        rendered_profiles={
            profile.name: profile,
        },
        raw_rendered_profiles={
            profile.name: raw_profile,
        }
        if raw_profile is not None
        else None,
        raw_profiles=profile_file.raw_profiles,
        omit_reference_defaults=False,
        omit_builtin_defaults_for_rendered=False,
    )
    return path


def write_profile_to_path(
    path: Path,
    profile: Profile,
    *,
    force: bool = False,
    raw_profile: dict[str, Any] | None = None,
) -> Path:
    profile_file = load_profile_file(path)
    if profile.name in profile_file.profiles and not force:
        raise FileExistsError(f"profile already exists: {profile.name}")
    if raw_profile is None:
        raw_profile = profile_file.raw_profiles.get(profile.name)
    _write_profile_file(
        path,
        defaults=profile_file.defaults,
        raw_defaults=profile_file.raw_defaults if profile_file.defaults is not None else None,
        rendered_profiles={
            profile.name: profile,
        },
        raw_rendered_profiles={
            profile.name: raw_profile,
        }
        if raw_profile is not None
        else None,
        raw_profiles=profile_file.raw_profiles,
        omit_reference_defaults=True,
    )
    return path


def delete_user_profile(name: str, *, home: Path | None = None) -> Path:
    path = user_config_path(home)
    profile_file = load_profile_file(path)
    if name not in profile_file.profiles:
        raise FileNotFoundError(f"profile not found: {name}")
    raw_profiles = dict(profile_file.raw_profiles)
    del raw_profiles[name]
    _write_profile_file(
        path,
        defaults=profile_file.defaults,
        raw_defaults=profile_file.raw_defaults if profile_file.defaults is not None else None,
        rendered_profiles={},
        raw_profiles=raw_profiles,
    )
    return path


def clone_user_profile(
    source_name: str,
    target_name: str,
    *,
    cwd: Path,
    home: Path | None = None,
    force: bool = False,
) -> Path:
    if source_name == target_name:
        raise ValueError("clone target must be different from source profile")
    source = resolve_profile(source_name, cwd=cwd, home=home, require_implemented=False)
    source_file = load_profile_file(Path(source.source)) if source.source is not None else None
    raw_source_profile = source_file.raw_profiles.get(source_name) if source_file is not None else None
    cloned = replace(source, name=target_name, source=None)
    return write_user_profile(cloned, home=home, force=force, raw_profile=raw_source_profile)


def prompt_for_new_profile(
    name: str,
    *,
    input_fn: Callable[[str], str] | None = None,
) -> Profile:
    input_fn = input_fn or input
    print(f"Creating RevRem profile: {name}")
    description = _prompt_text(input_fn, "Description", default="")
    harness = _prompt_choice(
        input_fn,
        "Harness",
        choices=tuple(HARNESS_REGISTRY),
        default="codex",
    )
    review_model = _prompt_text(input_fn, "Review model", default="")
    remediation_model = _prompt_text(input_fn, "Remediation model", default="")
    reasoning_effort = _prompt_choice(
        input_fn,
        "Reasoning effort",
        choices=REASONING_EFFORT_CHOICES,
        default="medium",
    )
    timeout_seconds = _prompt_timeout(input_fn, "Timeout seconds", default=1800)
    check = _prompt_text(input_fn, "First check command", default="")
    checks = (check,) if check else ()
    return Profile(
        name=name,
        description=description,
        pipeline=PipelineConfig(checks=checks),
        review=PhaseConfig(
            harness=harness,
            model=review_model or None,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
        ),
        remediation=PhaseConfig(
            harness=harness,
            model=remediation_model or None,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
        ),
    )


def _prompt_text(input_fn: Callable[[str], str], label: str, *, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input_fn(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_choice(
    input_fn: Callable[[str], str],
    label: str,
    *,
    choices: tuple[str, ...],
    default: str,
) -> str:
    choices_text = "/".join(choices)
    while True:
        value = input_fn(f"{label} ({choices_text}) [{default}]: ").strip() or default
        if value in choices:
            return value
        print(f"ERROR: {label.lower()} must be one of: {', '.join(choices)}", file=sys.stderr)


def _prompt_timeout(
    input_fn: Callable[[str], str],
    label: str,
    *,
    default: float,
) -> float | None:
    while True:
        value = input_fn(f"{label} [{default:g}; 0 disables]: ").strip()
        if not value:
            return default
        try:
            timeout_seconds = float(value)
        except ValueError:
            print(f"ERROR: {label.lower()} must be a number", file=sys.stderr)
            continue
        if timeout_seconds < 0:
            print(f"ERROR: {label.lower()} must be 0 or greater", file=sys.stderr)
            continue
        return None if timeout_seconds == 0 else timeout_seconds


def import_user_profiles(path: Path, *, home: Path | None = None, force: bool = False) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"profile import file not found: {path}")
    imported = load_profile_file(path)
    destination = user_config_path(home)
    current = load_profile_file(destination)
    raw_profiles = dict(current.raw_profiles)
    for name, profile in imported.profiles.items():
        if name in current.profiles and not force:
            raise FileExistsError(f"profile already exists: {name}")
        raw_profile = imported.raw_profiles.get(name, profile_to_dict(profile))
        raw_profiles[name] = _deep_merge(imported.raw_defaults, raw_profile)
    _write_profile_file(
        destination,
        defaults=current.defaults,
        raw_defaults=current.raw_defaults if current.defaults is not None else None,
        rendered_profiles={},
        raw_profiles=raw_profiles,
    )
    return destination


def minimal_profile(name: str, *, description: str = "") -> Profile:
    return Profile(name=name, description=description)


def validate_profile(profile: Profile, *, require_implemented: bool) -> None:
    if profile.pipeline.max_iterations < 1:
        raise ValueError("pipeline.max_iterations must be at least 1")
    for phase_name, phase in (("review", profile.review), ("remediation", profile.remediation)):
        if phase.timeout_seconds is not None and phase.timeout_seconds < 0:
            raise ValueError(f"{phase_name}.timeout_seconds must be 0 or greater")
    if profile.triage.timeout_seconds is not None and profile.triage.timeout_seconds < 0:
        raise ValueError("triage.timeout_seconds must be 0 or greater")
    if profile.runtime.exec_sandbox not in EXEC_SANDBOX_CHOICES:
        known = ", ".join(EXEC_SANDBOX_CHOICES)
        raise ValueError(f"runtime.exec_sandbox must be one of: {known}")
    if profile.runtime.exec_color not in EXEC_COLOR_CHOICES:
        known = ", ".join(EXEC_COLOR_CHOICES)
        raise ValueError(f"runtime.exec_color must be one of: {known}")
    if profile.runtime.max_remediation_input_chars < 1:
        raise ValueError("runtime.max_remediation_input_chars must be positive")
    if profile.runtime.terminal_excerpt_chars < 1:
        raise ValueError("runtime.terminal_excerpt_chars must be positive")
    if require_implemented:
        require_implemented_harness(profile.review.harness, field="review.harness")
        require_implemented_harness(profile.remediation.harness, field="remediation.harness")
        if profile.triage.enabled:
            require_implemented_harness(profile.triage.harness, field="triage.harness")
        if profile.commit.enabled:
            require_implemented_harness(profile.commit.harness, field="commit.harness")


def _write_profile_file(
    path: Path,
    *,
    defaults: Profile | None,
    raw_defaults: dict[str, Any] | None = None,
    rendered_profiles: dict[str, Profile],
    raw_rendered_profiles: dict[str, dict[str, Any]] | None = None,
    raw_profiles: dict[str, dict[str, Any]] | None = None,
    omit_reference_defaults: bool = False,
    omit_builtin_defaults_for_rendered: bool = True,
) -> None:
    blocks: list[str] = []
    if raw_defaults is not None:
        blocks.append(_raw_profile_to_toml_impl(raw_defaults, root=("defaults",)).rstrip())
    elif defaults is not None:
        blocks.append(
            _profile_to_toml_impl(defaults, root=("defaults",), omit_builtin_defaults=True).rstrip()
        )
    raw_profiles = raw_profiles or {}
    for name in sorted(set(raw_profiles) | set(rendered_profiles)):
        if name in rendered_profiles:
            blocks.append(
                _profile_to_toml_impl(
                    rendered_profiles[name],
                    root=("profiles", name),
                    omit_builtin_defaults=omit_builtin_defaults_for_rendered,
                    omit_reference_defaults=omit_reference_defaults,
                    reference=defaults,
                    raw_profile=(raw_rendered_profiles or {}).get(name),
                ).rstrip()
            )
        else:
            blocks.append(_raw_profile_to_toml_impl(raw_profiles[name], root=("profiles", name)).rstrip())
    _atomic_write_text(path, "\n\n".join(blocks) + "\n")


def _nest_dict(root: tuple[str, ...], inner: dict[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    current = nested
    for key in root:
        current[key] = {}
        current = current[key]
    current.update(inner)
    return nested


def _raw_profile_to_toml_impl(raw: dict[str, Any], *, root: tuple[str, ...]) -> str:
    return toml_dumps(_nest_dict(root, raw))


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except Exception:
            os.close(fd)
            raise
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(FileNotFoundError):
            shutil.copymode(path, tmp_path)
        tmp_path.replace(path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)
    except Exception:
        with suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def _merge_dataclass(base: Any, override: Any) -> Any:
    values = asdict(base)
    defaults = asdict(type(override)())
    for key, value in asdict(override).items():
        if value != defaults[key]:
            values[key] = value
    return type(base)(**values)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _reject_unknown_keys(raw: dict[str, Any], allowed: tuple[str, ...], field: str) -> None:
    unexpected = sorted(key for key in raw if key not in allowed)
    if unexpected:
        keys = ", ".join(unexpected)
        raise ValueError(f"{field} contains unknown keys: {keys}")


def _table(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a table")
    return value


def _str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _str(value, field)


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return int(value)


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _int(value, field)


def _float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a number")
    return float(value)


def _optional_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _float(value, field)


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{field} must be a decimal number")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
