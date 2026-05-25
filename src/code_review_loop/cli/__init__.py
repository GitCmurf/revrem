"""Console entry point for RevRem.

Wave C moves the review loop implementation to :mod:`code_review_loop.loop`.
This package remains the console-script target while tests and command modules
are migrated to final homes.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from code_review_loop import __version__ as __version__


def __getattr__(name: str) -> Any:
    loop = import_module("code_review_loop.loop")
    try:
        return getattr(loop, name)
    except AttributeError:
        raise AttributeError(f"module 'code_review_loop.cli' has no attribute {name!r}") from None


def main(argv: list[str] | None = None) -> int:
    from code_review_loop.loop import main as loop_main

    return loop_main(argv)
