"""Console entry point for RevRem."""

from __future__ import annotations

from code_review_loop import __version__ as __version__


def main(argv: list[str] | None = None) -> int:
    from code_review_loop.loop import main as loop_main

    return loop_main(argv)
