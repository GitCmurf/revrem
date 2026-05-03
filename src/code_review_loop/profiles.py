"""TOML profile loading and resolution for RevRem."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from code_review_loop import run_history
from code_review_loop.harnesses import require_implemented_harness, validate_harness_name

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
)
PIPELINE_KEYS = ("base", "max_iterations", "final_review", "checks")
PHASE_KEYS = ("harness", "model", "reasoning_effort", "timeout_seconds")
TRIAGE_KEYS = ("enabled", "harness", "model", "reasoning_effort", "timeout_seconds", "prompt")
COMMIT_KEYS = ("enabled", "harness", "message_model", "message_prompt")
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
    commit: CommitConfig = field(default_factory=CommitConfig)
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


@dataclass(frozen=True)
class ProfileListItem:
    name: str
    description: str
    source: str | None
    last_used_at: str | None


def user_config_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path(os.environ.get("HOME", "~")).expanduser()
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
    return TriageConfig(
        enabled=_bool(raw.get("enabled", False), f"{field}.enabled"),
        harness=harness,
        model=_optional_str(raw.get("model"), f"{field}.model"),
        reasoning_effort=reasoning_effort,
        timeout_seconds=_optional_float(raw.get("timeout_seconds"), f"{field}.timeout_seconds"),
        prompt=_optional_str(raw.get("prompt"), f"{field}.prompt"),
    )


def parse_commit(raw: dict[str, Any]) -> CommitConfig:
    _reject_unknown_keys(raw, COMMIT_KEYS, "commit")
    harness = _str(raw.get("harness", "codex"), "commit.harness")
    validate_harness_name(harness, field="commit.harness")
    return CommitConfig(
        enabled=_bool(raw.get("enabled", False), "commit.enabled"),
        harness=harness,
        message_model=_optional_str(raw.get("message_model"), "commit.message_model")
        or "gpt-5.3-codex-spark",
        message_prompt=_optional_str(raw.get("message_prompt"), "commit.message_prompt"),
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


def resolve_profile(
    name: str,
    *,
    cwd: Path,
    home: Path | None = None,
    require_implemented: bool = True,
) -> Profile:
    user_file = load_profile_file(user_config_path(home))
    project_file = load_profile_file(project_config_path(cwd))
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


def resolve_defaults(*, cwd: Path, home: Path | None = None) -> Profile:
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
    validate_profile(defaults, require_implemented=True)
    return defaults


def list_profiles(*, cwd: Path, home: Path | None = None) -> list[Profile]:
    files = [load_profile_file(user_config_path(home)), load_profile_file(project_config_path(cwd))]
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
    result = profiles[0]
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
            source=profile.source or result.source,
        )
    return result


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return asdict(profile)


def profile_to_json(profile: Profile) -> str:
    return json.dumps(profile_to_dict(profile), indent=2, sort_keys=True) + "\n"


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


def _profile_to_toml_impl(
    profile: Profile,
    *,
    root: tuple[str, ...] | None,
    omit_builtin_defaults: bool,
    omit_reference_defaults: bool = False,
    reference: Profile | None = None,
) -> str:
    lines: list[str] = []
    if root is not None:
        lines.append(f"[{_toml_table_header(root)}]")
        if profile.description:
            lines.append(f"description = {_toml_string(profile.description)}")
            lines.append("")
    elif profile.description:
        lines.append(f"description = {_toml_string(profile.description)}")
        lines.append("")
    for section_name in ("pipeline", "review", "triage", "remediation", "commit", "output", "runtime"):
        value = getattr(profile, section_name)
        header = (*root, section_name) if root is not None else (section_name,)
        section_lines: list[str] = []
        defaults = type(value)()
        reference_value = getattr(reference, section_name) if reference is not None else None
        for key, item in asdict(value).items():
            if item is None:
                continue
            if omit_builtin_defaults and item == getattr(defaults, key):
                continue
            if omit_reference_defaults and reference_value is not None and item == getattr(reference_value, key):
                continue
            section_lines.append(f"{key} = {_toml_value(item)}")
        if not section_lines:
            continue
        lines.append(f"[{_toml_table_header(header)}]")
        lines.extend(section_lines)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_user_profile(profile: Profile, *, home: Path | None = None, force: bool = False) -> Path:
    path = user_config_path(home)
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
    raw_profiles: dict[str, dict[str, Any]] | None = None,
    omit_reference_defaults: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                    omit_builtin_defaults=True,
                    omit_reference_defaults=omit_reference_defaults,
                    reference=defaults,
                ).rstrip()
            )
        else:
            blocks.append(_raw_profile_to_toml_impl(raw_profiles[name], root=("profiles", name)).rstrip())
    _atomic_write_text(path, "\n\n".join(blocks) + "\n")


def _raw_profile_to_toml_impl(raw: dict[str, Any], *, root: tuple[str, ...]) -> str:
    lines: list[str] = []
    if root:
        lines.append(f"[{_toml_table_header(root)}]")
    nested_tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in raw.items():
        if isinstance(value, dict):
            nested_tables.append((key, value))
            continue
        lines.append(f"{_toml_key_segment(key)} = {_toml_value(value)}")
    for key, value in nested_tables:
        nested = _raw_profile_to_toml_impl(value, root=(*root, key))
        if nested:
            lines.append("")
            lines.append(nested.rstrip())
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
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


def _optional_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
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


def _toml_table_header(path: tuple[str, ...]) -> str:
    return ".".join(_toml_key_segment(segment) for segment in path)


def _toml_key_segment(value: str) -> str:
    if TOML_BARE_KEY_RE.fullmatch(value):
        return value
    return json.dumps(value)
