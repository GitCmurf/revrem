"""Effective timeout resolution for routed remediation."""

from __future__ import annotations

from code_review_loop.adapters.phase_support import phase_timeout_seconds
from code_review_loop.config import LoopConfig
from code_review_loop.core.routing_types import ResolvedRoute


def effective_route_timeout_seconds(
    config: LoopConfig,
    resolved_route: ResolvedRoute,
) -> float | None:
    """Return the subprocess timeout for routed remediation.

    Route timeouts preserve their profile semantics, but an explicit CLI
    remediation/global timeout acts as an upper bound. This keeps watched
    dogfood invocations like ``--timeout-seconds 600`` from being bypassed by
    a profile route that was saved as ``timeout_seconds = 0``.
    """
    route_timeout = phase_timeout_seconds(config, resolved_route.timeout_seconds)
    cli_cap = explicit_cli_remediation_timeout_cap(config)
    if cli_cap is None:
        return route_timeout
    if route_timeout is None:
        return cli_cap
    return min(route_timeout, cli_cap)


def effective_route_timeout_display(
    config: LoopConfig,
    resolved_route: ResolvedRoute,
) -> float:
    timeout = effective_route_timeout_seconds(config, resolved_route)
    return 0 if timeout is None else timeout


def explicit_cli_remediation_timeout_cap(config: LoopConfig) -> float | None:
    source = config.phase_config_field_sources.get("remediation", {}).get("timeout_seconds")
    if source != "cli":
        return None
    return config.remediation_timeout_seconds
