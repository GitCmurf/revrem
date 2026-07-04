"""Pure view-models for the TUI prompts library."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class PromptAsset:
    name: str
    kind: str
    trust: str
    preview: str


def prompt_inventory() -> tuple[PromptAsset, ...]:
    root = files("code_review_loop.prompts")
    fragments: list[PromptAsset] = []
    fragment_dir = root.joinpath("fragments")
    for entry in sorted(item.name for item in fragment_dir.iterdir() if item.name.endswith(".txt")):
        name = entry.removesuffix(".txt")
        text = fragment_dir.joinpath(entry).read_text(encoding="utf-8")
        fragments.append(
            PromptAsset(
                name=name,
                kind="fragment",
                trust="builtin",
                preview=_preview(text),
            )
        )
    contracts: list[PromptAsset] = []
    for entry in sorted(
        item.name
        for item in root.iterdir()
        if item.name.startswith("triage_v") and item.name.endswith(".txt")
    ):
        name = entry.removesuffix(".txt")
        text = root.joinpath(entry).read_text(encoding="utf-8")
        contracts.append(
            PromptAsset(
                name=name,
                kind="contract",
                trust="builtin",
                preview=_preview(text),
            )
        )
    return tuple(fragments) + tuple(contracts)


def prompt_field_label(phase: str, harness: str | None, value: str | None) -> str:
    if phase == "review" and harness == "codex":
        return "built-in review (codex)"
    if value:
        return value
    return "<default>"


def _preview(text: str, *, limit: int = 80) -> str:
    flattened = " ".join(text.split())
    return flattened[:limit]
