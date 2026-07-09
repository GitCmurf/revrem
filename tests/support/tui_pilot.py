from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from code_review_loop import profiles, tui, tui_state

_TEXTUAL_UNAVAILABLE_PREFIX = "ERROR: revrem ui requires the optional Textual dependency."


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
) -> AsyncIterator[tuple[object, object]]:
    previous_fake = os.environ.get("REVREM_ALLOW_FAKE_HARNESS")
    if fake_harness:
        os.environ["REVREM_ALLOW_FAKE_HARNESS"] = "1"
    else:
        os.environ.pop("REVREM_ALLOW_FAKE_HARNESS", None)
    try:
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
        async with app.run_test(size=size or (80, 24)) as pilot:
            yield app, pilot
    finally:
        if previous_fake is None:
            os.environ.pop("REVREM_ALLOW_FAKE_HARNESS", None)
        else:
            os.environ["REVREM_ALLOW_FAKE_HARNESS"] = previous_fake
