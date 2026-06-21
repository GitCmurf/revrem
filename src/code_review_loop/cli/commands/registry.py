"""CLI subcommand registry.

This module is the command-driver registry and deliberately owns the concrete
``ui`` -> ``tui.main`` coupling with the other subcommand names. Keeping the
table here leaves ``cli.main`` closed to new concrete subcommands.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence


def build_subcommand_registry() -> dict[str, Callable[[Sequence[str]], int]]:
    from code_review_loop import tui as _tui
    from code_review_loop.cli.commands import (
        bundle,
        checks,
        config,
        doctor,
        history,
        install_hooks,
        policy,
        replay,
        report,
        resume,
        suppress,
        triage,
    )

    return {
        "bundle-bug-report": bundle.main,
        "checks": checks.main,
        "config": config.main,
        "doctor": doctor.main,
        "history": history.main,
        "install-hooks": install_hooks.main,
        "policy": policy.main,
        "preflight": doctor.main,
        "replay": replay.main,
        "report": report.main,
        "resume": resume.main,
        "suppress": suppress.main,
        "triage": triage.main,
        "ui": _tui.main,
    }


def dispatch_or_none(argv: Sequence[str]) -> int | None:
    """Dispatch a concrete subcommand when ``argv`` starts with one."""

    if not argv:
        return None
    handler = build_subcommand_registry().get(argv[0])
    if handler is None:
        return None
    return handler(argv[1:])
