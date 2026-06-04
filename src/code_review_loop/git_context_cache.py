"""Per-run mutable cache for git preflight results.

Lives at the root of the package so it can be referenced from
``code_review_loop.core.ports.RunContext`` without dragging the
``adapters`` layer (or any of its transitive imports) into the core
import graph. The cache is wired up in
``code_review_loop.runner_setup.create_run_context`` and consumed by
``code_review_loop.adapters.review`` (``build_external_review_context`` and
``review_base_preflight_error``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GitContextCache:
    """Per-run cache for git preflight results shared by review preflight and
    the external-review context builder.

    Mutable by design: the cache reference is shared across the run via
    ``RunContext.git_context_cache`` (analogous to ``BudgetState``) and is
    expected to be created once per run by
    ``runner_setup.create_run_context``.

    Keyed by ``(cwd, base)`` for the cheap base/merge-base lookups and by
    ``(cwd, base, head)`` for the expensive ``base...HEAD`` diffs. The HEAD
    SHA is intentionally NOT cached: callers must always re-run
    ``git rev-parse HEAD`` so that the live HEAD (which advances every
    remediation commit) is used to key the per-head diff buckets. The
    per-head diff buckets invalidate naturally because their key includes
    the SHA, so a fresh remediation commit yields a fresh cache entry on
    the next review iteration.
    """

    base_commit: dict[tuple[str, str], str] = field(default_factory=dict)
    merge_base: dict[tuple[str, str, str], str] = field(default_factory=dict)
    base_head_diff: dict[tuple[str, str, str], str] = field(default_factory=dict)
    base_head_diff_stat: dict[tuple[str, str, str], str] = field(default_factory=dict)
    base_head_diff_name_status: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )
