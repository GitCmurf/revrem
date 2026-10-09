from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import pytest

from code_review_loop import profiles, tui, tui_state

_TEXTUAL_UNAVAILABLE_PREFIX = "ERROR: revrem ui requires the optional Textual dependency."
CANONICAL_TUI_THEME = "textual-dark"
_MISSING = object()


@contextmanager
def tui_test_environment(*, no_color: bool = False, theme: str = CANONICAL_TUI_THEME):
    """Make Textual rendering independent of the invoking shell."""
    previous_no_color = os.environ.get("NO_COLOR", _MISSING)
    previous_theme = os.environ.get("TEXTUAL_THEME", _MISSING)
    if no_color:
        os.environ["NO_COLOR"] = "1"
    else:
        os.environ.pop("NO_COLOR", None)
    os.environ["TEXTUAL_THEME"] = theme
    try:
        yield
    finally:
        _restore_environment("NO_COLOR", previous_no_color)
        _restore_environment("TEXTUAL_THEME", previous_theme)


def configure_test_app(app: Any, *, theme: str = CANONICAL_TUI_THEME) -> None:
    """Apply the canonical theme after Textual's import-time defaults."""
    app.theme = theme


def _restore_environment(name: str, value: object) -> None:
    if value is _MISSING:
        os.environ.pop(name, None)
    else:
        os.environ[name] = str(value)


def _require_textual_app() -> type[object]:
    pytest.importorskip("textual", reason="Textual optional dependency is not installed.")
    try:
        return tui.textual_app_class()
    except RuntimeError as exc:
        if _TEXTUAL_UNAVAILABLE_PREFIX in str(exc):
            pytest.skip(str(exc))
        raise


@asynccontextmanager
async def pilot_app(
    *,
    cwd: Path,
    home: Path | None = None,
    profile_name: str | None = None,
    fake_harness: bool = True,
    size: tuple[int, int] | None = None,
    skip_splash: bool = True,
    theme: str = CANONICAL_TUI_THEME,
    no_color: bool = False,
) -> AsyncIterator[tuple[object, object]]:
    previous_fake = os.environ.get("REVREM_ALLOW_FAKE_HARNESS")
    if fake_harness:
        os.environ["REVREM_ALLOW_FAKE_HARNESS"] = "1"
    else:
        os.environ.pop("REVREM_ALLOW_FAKE_HARNESS", None)
    try:
        with tui_test_environment(no_color=no_color, theme=theme):
            model = tui_state.build_shell_model(
                cwd=cwd,
                home=home,
                selected_profile_name=profile_name,
            )
            profiles_by_name = {
                profile.name: profile
                for profile in profiles.resolve_profiles(
                    cwd=cwd,
                    home=home,
                    require_implemented=False,
                    include_builtins=True,
                )
            }
            app = _require_textual_app()(
                model=model,
                profiles_by_name=profiles_by_name,
                skip_splash=skip_splash,
            )
            configure_test_app(app, theme=theme)
            async with app.run_test(size=size or (80, 24)) as pilot:
                yield app, pilot
    finally:
        if previous_fake is None:
            os.environ.pop("REVREM_ALLOW_FAKE_HARNESS", None)
        else:
            os.environ["REVREM_ALLOW_FAKE_HARNESS"] = previous_fake
