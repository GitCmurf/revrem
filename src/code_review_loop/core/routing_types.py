"""Pure routing/profile DTOs (REVREM-TASK-003 B1b, B2a).

All classes are frozen dataclasses with no I/O. Lifted from profiles.py so that
policy.py can import them without pulling in the edge module. ``profiles.py``
imports these DTOs as its canonical profile data model.

`ResolvedRoute` was originally in policy.py; moved here (pre-B2a) so that
`core/phase_types.py` can reference it without depending on an edge module.
``policy.py`` imports it from this core DTO module.

This module imports only the standard library (Contract C4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

COMMIT_ON_HOOK_FAILURE_CHOICES = ("remediate", "stop", "no-verify")


@dataclass(frozen=True)
class PhaseConfig:
    harness: str = "codex"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class TriageRouteConfig:
    harness: str = "codex"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    sandbox: str = "workspace-write"
    fallback: str | None = None


@dataclass(frozen=True)
class TriageRoutingRuleWhen:
    domain_tags_any: tuple[str, ...] = field(default_factory=tuple)
    risk_level_min: str | None = None
    risk_level_max: str | None = None
    refactor_depth_any: tuple[str, ...] = field(default_factory=tuple)
    module_count_gte: int | None = None
    module_count_lt: int | None = None
    safety_signals_any: tuple[str, ...] = field(default_factory=tuple)
    failed_checks_any: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TriageRoutingRuleThen:
    route: str | None = None
    prompt_fragments: tuple[str, ...] = field(default_factory=tuple)
    allow_model_deescalation: bool = True
    allow_model_escalation: bool | None = None


@dataclass(frozen=True)
class TriageRoutingRule:
    id: str
    when: TriageRoutingRuleWhen = field(default_factory=TriageRoutingRuleWhen)
    then: TriageRoutingRuleThen = field(default_factory=TriageRoutingRuleThen)


@dataclass(frozen=True)
class TriageRoutingConfig:
    enabled: bool = False
    mode: str = "first-match"
    default_route: str = "midtier-coder"
    strict_on_unavailable_route: bool = True
    rule: tuple[TriageRoutingRule, ...] = field(default_factory=tuple)
    allow_model_escalation: bool = True


@dataclass(frozen=True)
class TriageConfig:
    enabled: bool = False
    harness: str = "codex"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    prompt: str | None = None
    on_invalid: str = "continue"
    contract: str = "v1"
    routing: TriageRoutingConfig = field(default_factory=TriageRoutingConfig)
    routes: dict[str, TriageRouteConfig] = field(default_factory=dict)


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
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None


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
    harness_executables: dict[str, str] = field(default_factory=dict)
    exec_sandbox: str = "workspace-write"
    exec_color: str = "never"
    exec_json: bool = False
    output_last_message: bool = True
    full_auto: bool = True
    max_remediation_input_chars: int = 200_000
    external_review_input_chars: int = 80_000
    external_review_warning_seconds: float = 1_800
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


@dataclass(frozen=True)
class ResolvedRoute:
    """The routing decision produced by resolve_routing (moved from policy.py pre-B2a).

    Originally lived in policy.py; moved here so core phase types can reference
    it without importing an edge module.
    """

    route_tier: str
    harness: str
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    sandbox: str = "workspace-write"
    prompt_fragments: tuple[str, ...] = field(default_factory=tuple)
    allow_model_deescalation: bool = True
    rule_id: str | None = None
    fallbacks_considered: tuple[str, ...] = field(default_factory=tuple)
    fallback_applied: str | None = None
