"""Pin the intended public surface of the package (REVREM-TASK-003 Contract C1).

The God-object refactor moves symbols between modules wave by wave. This test
asserts two things stay true throughout:

1. The console-script entry point ``code_review_loop.cli:main`` always resolves.
2. The small *intended* public API is importable.

During Waves A-B the names live in ``code_review_loop.cli``; as symbols move to
their final homes (``core/``, ``cli/``) the final-home assertions are added
here and the transitional ones removed. Today everything is still in ``cli``.
"""

from __future__ import annotations

import importlib

import pytest

# The intended public API. Everything else tests reach into is *internal* and
# is being retired (see C1/C2). Keep this list small on purpose.
INTENDED_PUBLIC_NAMES = (
    "main",
    "run_loop",
    "LoopConfig",
    "CommandResult",
    "__version__",
)


def test_entry_point_target_resolves() -> None:
    """``code_review_loop.cli:main`` is the entry point for both scripts."""
    module = importlib.import_module("code_review_loop.cli")
    main = getattr(module, "main", None)
    assert callable(main), "code_review_loop.cli:main must resolve to a callable"


@pytest.mark.parametrize("name", INTENDED_PUBLIC_NAMES)
def test_intended_public_name_importable(name: str) -> None:
    module = importlib.import_module("code_review_loop.cli")
    assert hasattr(module, name), f"intended public symbol cli.{name} is missing"


def test_package_version_is_exposed() -> None:
    pkg = importlib.import_module("code_review_loop")
    assert isinstance(pkg.__version__, str) and pkg.__version__
    cli = importlib.import_module("code_review_loop.cli")
    # cli re-exports __version__; the two must agree.
    assert cli.__version__ == pkg.__version__
