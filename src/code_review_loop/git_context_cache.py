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
    SHA is cached per ``cwd`` for the duration of a single phase (see
    ``head_sha`` below) and invalidated via ``invalidate_head_sha`` at
    phase boundaries such as the start of each review or remediation
    phase. The per-head diff buckets invalidate naturally because their key
    includes the SHA, so a fresh remediation commit yields a fresh cache
    entry on the next review iteration.
    """

    base_commit: dict[tuple[str, str], str] = field(default_factory=dict)
    merge_base: dict[tuple[str, str, str], str] = field(default_factory=dict)
    base_head_diff: dict[tuple[str, str, str], str] = field(default_factory=dict)
    base_head_diff_stat: dict[tuple[str, str, str], str] = field(default_factory=dict)
    base_head_diff_name_status: dict[tuple[str, str, str], str] = field(default_factory=dict)
    head_sha: dict[str, str] = field(default_factory=dict)

    def invalidate_head_sha(self, cwd: str | None = None) -> None:
        """Drop the cached HEAD SHA for ``cwd`` (or every cwd if omitted)."""
        if cwd is None:
            self.head_sha.clear()
        else:
            self.head_sha.pop(cwd, None)
