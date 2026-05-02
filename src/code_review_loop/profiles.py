"""TOML profile loading and resolution for RevRem."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from code_review_loop.harnesses import require_implemented_harness, validate_harness_name

USER_CONFIG_RELATIVE = Path(".config") / "revrem" / "profiles.toml"
PROJECT_CONFIG_NAME = ".revrem.toml"


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
    prompt: str | None = None


@dataclass(frozen=True)
class PipelineConfig:
    base: str = "main"
    max_iterations: int = 2
    final_review: bool = True
    checks: tuple[str, ...] = field(default_factory=tuple)


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
class Profile:
    name: str
    description: str = ""
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    review: PhaseConfig = field(default_factory=PhaseConfig)
    triage: TriageConfig = field(default_factory=TriageConfig)
    remediation: PhaseConfig = field(default_factory=PhaseConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    source: str | None = None


@dataclass(frozen=True)
class ProfileFile:
    path: Path
    profiles: dict[str, Profile]
    raw_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    defaults: Profile | None = None
    raw_defaults: dict[str, Any] = field(default_factory=dict)


def user_config_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path(os.environ.get("HOME", "~")).expanduser()
    return root / USER_CONFIG_RELATIVE


def project_config_path(cwd: Path) -> Path:
    return cwd / PROJECT_CONFIG_NAME


def load_profile_file(path: Path) -> ProfileFile:
    if not path.is_file():
        return ProfileFile(path=path, profiles={})
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"profile file is not a TOML table: {path}")
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
    description = _optional_str(raw.get("description"), f"{name}.description") or ""
    pipeline = parse_pipeline(_table(raw.get("pipeline", {}), f"{name}.pipeline"))
    review = parse_phase(_table(raw.get("review", {}), f"{name}.review"), f"{name}.review")
    triage = parse_triage(_table(raw.get("triage", {}), f"{name}.triage"), f"{name}.triage")
    remediation = parse_phase(
        _table(raw.get("remediation", {}), f"{name}.remediation"),
        f"{name}.remediation",
    )
    output = parse_output(_table(raw.get("output", {}), f"{name}.output"))
    runtime = parse_runtime(_table(raw.get("runtime", {}), f"{name}.runtime"))
    profile = Profile(
        name=name,
        description=description,
        pipeline=pipeline,
        review=review,
        triage=triage,
        remediation=remediation,
        output=output,
        runtime=runtime,
        source=source,
    )
    validate_profile(profile, require_implemented=False)
    return profile


def parse_pipeline(raw: dict[str, Any]) -> PipelineConfig:
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
    harness = _str(raw.get("harness", "codex"), f"{field}.harness")
    validate_harness_name(harness, field=f"{field}.harness")
    return PhaseConfig(
        harness=harness,
        model=_optional_str(raw.get("model"), f"{field}.model"),
        reasoning_effort=_optional_str(raw.get("reasoning_effort"), f"{field}.reasoning_effort"),
        timeout_seconds=_optional_float(raw.get("timeout_seconds"), f"{field}.timeout_seconds"),
    )


def parse_triage(raw: dict[str, Any], field: str) -> TriageConfig:
    harness = _str(raw.get("harness", "codex"), f"{field}.harness")
    validate_harness_name(harness, field=f"{field}.harness")
    return TriageConfig(
        enabled=_bool(raw.get("enabled", False), f"{field}.enabled"),
        harness=harness,
        model=_optional_str(raw.get("model"), f"{field}.model"),
        prompt=_optional_str(raw.get("prompt"), f"{field}.prompt"),
    )


def parse_output(raw: dict[str, Any]) -> OutputConfig:
    summary_format = _str(raw.get("summary_format", "text"), "output.summary_format")
    if summary_format not in {"text", "json", "both"}:
        raise ValueError("output.summary_format must be text, json, or both")
    progress_style = _str(raw.get("progress_style", "compact"), "output.progress_style")
    if progress_style not in {"compact", "verbose"}:
        raise ValueError("output.progress_style must be compact or verbose")
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


def resolve_profile(name: str, *, cwd: Path, home: Path | None = None) -> Profile:
    user_file = load_profile_file(user_config_path(home))
    project_file = load_profile_file(project_config_path(cwd))
    raw: dict[str, Any] = {}
    source = None
    if name in user_file.profiles:
        raw = _deep_merge(raw, user_file.raw_profiles[name])
        source = str(user_file.path)
    if project_file.defaults is not None:
        raw = _deep_merge(raw, project_file.raw_defaults)
        source = str(project_file.path)
    if name in project_file.profiles:
        raw = _deep_merge(raw, project_file.raw_profiles[name])
        source = str(project_file.path)
    if not raw:
        raise FileNotFoundError(f"profile not found: {name}")
    resolved = parse_profile(name, raw, source=source)
    validate_profile(resolved, require_implemented=True)
    return resolved


def list_profiles(*, cwd: Path, home: Path | None = None) -> list[Profile]:
    files = [load_profile_file(user_config_path(home)), load_profile_file(project_config_path(cwd))]
    seen: dict[str, Profile] = {}
    for profile_file in files:
        for name, profile in profile_file.profiles.items():
            seen[name] = profile
    return [seen[name] for name in sorted(seen)]


def merge_profiles(name: str, *profiles: Profile) -> Profile:
    result = profiles[0]
    for profile in profiles[1:]:
        result = Profile(
            name=name,
            description=profile.description or result.description,
            pipeline=_merge_dataclass(result.pipeline, profile.pipeline),
            review=_merge_dataclass(result.review, profile.review),
            triage=_merge_dataclass(result.triage, profile.triage),
            remediation=_merge_dataclass(result.remediation, profile.remediation),
            output=_merge_dataclass(result.output, profile.output),
            runtime=_merge_dataclass(result.runtime, profile.runtime),
            source=profile.source or result.source,
        )
    return result


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return asdict(profile)


def profile_to_json(profile: Profile) -> str:
    return json.dumps(profile_to_dict(profile), indent=2, sort_keys=True) + "\n"


def profile_to_toml(profile: Profile, *, include_wrapper: bool = False) -> str:
    lines: list[str] = []
    prefix = f"profiles.{profile.name}." if include_wrapper else ""
    if include_wrapper:
        lines.append(f"[profiles.{profile.name}]")
        lines.append(f"description = {_toml_string(profile.description)}")
        lines.append("")
    elif profile.description:
        lines.append(f"description = {_toml_string(profile.description)}")
        lines.append("")
    for section_name in ("pipeline", "review", "triage", "remediation", "output", "runtime"):
        value = getattr(profile, section_name)
        lines.append(f"[{prefix}{section_name}]")
        for key, item in asdict(value).items():
            if item is None:
                continue
            lines.append(f"{key} = {_toml_value(item)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_user_profile(profile: Profile, *, home: Path | None = None, force: bool = False) -> Path:
    path = user_config_path(home)
    profile_file = load_profile_file(path)
    if profile.name in profile_file.profiles and not force:
        raise FileExistsError(f"profile already exists: {profile.name}")
    profiles = dict(profile_file.profiles)
    profiles[profile.name] = profile
    _write_profiles(path, profiles)
    return path


def delete_user_profile(name: str, *, home: Path | None = None) -> Path:
    path = user_config_path(home)
    profile_file = load_profile_file(path)
    if name not in profile_file.profiles:
        raise FileNotFoundError(f"profile not found: {name}")
    profiles = dict(profile_file.profiles)
    del profiles[name]
    _write_profiles(path, profiles)
    return path


def import_user_profiles(path: Path, *, home: Path | None = None, force: bool = False) -> Path:
    imported = load_profile_file(path)
    destination = user_config_path(home)
    current = load_profile_file(destination)
    profiles = dict(current.profiles)
    for name, profile in imported.profiles.items():
        if name in profiles and not force:
            raise FileExistsError(f"profile already exists: {name}")
        profiles[name] = profile
    _write_profiles(destination, profiles)
    return destination


def minimal_profile(name: str, *, description: str = "") -> Profile:
    return Profile(name=name, description=description)


def validate_profile(profile: Profile, *, require_implemented: bool) -> None:
    if profile.pipeline.max_iterations < 1:
        raise ValueError("pipeline.max_iterations must be at least 1")
    if profile.runtime.max_remediation_input_chars < 1:
        raise ValueError("runtime.max_remediation_input_chars must be positive")
    if profile.runtime.terminal_excerpt_chars < 1:
        raise ValueError("runtime.terminal_excerpt_chars must be positive")
    if require_implemented:
        require_implemented_harness(profile.review.harness, field="review.harness")
        require_implemented_harness(profile.remediation.harness, field="remediation.harness")
        if profile.triage.enabled:
            raise ValueError("triage profiles are valid but triage execution is not implemented yet")


def _write_profiles(path: Path, profiles: dict[str, Profile]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        profile_to_toml(profile, include_wrapper=True).rstrip()
        for _, profile in sorted(profiles.items())
    )
    path.write_text(content + "\n", encoding="utf-8")


def _merge_dataclass(base: Any, override: Any) -> Any:
    values = asdict(base)
    for key, value in asdict(override).items():
        default = asdict(type(override)()).get(key)
        if value != default:
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
    if not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"{field} must be a number")
    return float(value)


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, tuple | list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {value!r}")


def _toml_string(value: str) -> str:
    return json.dumps(value)
