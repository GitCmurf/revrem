"""Pin the intended public surface of the package (REVREM-TASK-003 Contract C1).

The God-object refactor moves symbols between modules wave by wave. This test
asserts two things stay true throughout:

1. The console-script entry point ``code_review_loop.cli.main:main`` always resolves.
2. The small *intended* public API is importable.

Wave C moves the library surface out of the CLI driver; only ``main`` remains
on ``code_review_loop.cli.main``.
"""

from __future__ import annotations

import importlib

import pytest


# The intended public API. Everything else tests reach into is *internal* and
# is being retired (see C1/C2). Keep this list small on purpose.
def test_entry_point_target_resolves() -> None:
    """``code_review_loop.cli.main:main`` is the entry point for both scripts."""
    module = importlib.import_module("code_review_loop.cli.main")
    main = getattr(module, "main", None)
    assert callable(main), "code_review_loop.cli.main:main must resolve to a callable"


@pytest.mark.parametrize(
    ("module_name", "name"),
    (
        ("code_review_loop.cli.main", "main"),
        ("code_review_loop.runner", "run_loop"),
        ("code_review_loop.config", "LoopConfig"),
        ("code_review_loop.core.ports", "CommandResult"),
    ),
)
def test_intended_public_name_importable(module_name: str, name: str) -> None:
    module = importlib.import_module(module_name)
    assert hasattr(module, name), f"intended public symbol {module_name}.{name} is missing"


def test_package_version_is_exposed() -> None:
    pkg = importlib.import_module("code_review_loop")
    assert isinstance(pkg.__version__, str) and pkg.__version__
    cli = importlib.import_module("code_review_loop.cli")
    # cli re-exports __version__; the two must agree.
    assert cli.__version__ == pkg.__version__
