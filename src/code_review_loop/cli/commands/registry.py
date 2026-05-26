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
        config,
        doctor,
        history,
        policy,
        replay,
        resume,
        suppress,
        triage,
    )

    return {
        "bundle-bug-report": bundle.main,
        "config": config.main,
        "doctor": doctor.main,
        "history": history.main,
        "policy": policy.main,
        "preflight": doctor.main,
        "replay": replay.main,
        "resume": resume.main,
        "suppress": suppress.main,
        "triage": triage.main,
        "ui": _tui.main,
    }
