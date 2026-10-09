"""Prompt asset resolution for the interactive TUI."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from code_review_loop import prompts_composer, tui_prompts_state


def prompt_asset_text(asset: tui_prompts_state.PromptAsset, *, cwd: Path) -> str:
    if asset.kind == "fragment":
        text = prompts_composer.load_fragment(cwd, asset.name, trusted_repo=False)
        if text is None:
            raise ValueError(f"prompt fragment is unavailable: {asset.name}")
        return text
    if asset.kind == "contract":
        return (
            files("code_review_loop.prompts")
            .joinpath(f"{asset.name}.txt")
            .read_text(encoding="utf-8")
        )
    raise ValueError(f"unknown prompt asset kind: {asset.kind}")
