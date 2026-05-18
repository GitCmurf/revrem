"""Remediation prompt composition engine."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from code_review_loop import policy


def compose_remediation_prompt(
    cwd: Path,
    triage_payload: dict[str, Any],
    resolved_route: policy.ResolvedRoute,
    original_review: str,
    max_chars: int = 200_000,
) -> str:
    fragments: list[str] = []
    
    # 1. System/Role Context (Baseline)
    fragments.append(REMEDIATION_ROLE_PROMPT)

    # 2. Policy-driven Fragments
    for frag_name in resolved_route.prompt_fragments:
        content = load_fragment(cwd, frag_name)
        if content:
            fragments.append(f"--- Fragment: {frag_name} ---\n{content}")

    # 3. Triage-prescribed Fragments
    triage_requirements = triage_payload.get("prompt_requirements", {})
    for frag_name in triage_requirements.get("required_fragments", []):
        if frag_name not in resolved_route.prompt_fragments:
             content = load_fragment(cwd, frag_name)
             if content:
                 fragments.append(f"--- Fragment: {frag_name} ---\n{content}")

    # 4. Triage Handoff (The specific instructions for this iteration)
    # This is "untrusted" model output, so we quote it clearly.
    fragments.append("--- Triage Handoff (Draft Instructions) ---")
    handoff_draft = triage_requirements.get("triage_prompt_draft", "")
    if handoff_draft:
        fragments.append(f"Instructions for this iteration:\n{handoff_draft}")
    
    fragments.append("--- Structured Classification & Context ---")
    classification = triage_payload.get("classification", {})
    fragments.append(f"Risk Level: {classification.get('risk_level')}")
    fragments.append(f"Refactor Depth: {classification.get('refactor_depth')}")
    
    dod = triage_requirements.get("definition_of_done", [])
    if dod:
        fragments.append("Definition of Done:")
        for item in dod:
            fragments.append(f"- {item}")

    # 5. Original Review Context (The "ground truth" findings)
    fragments.append("--- Original Review Context ---")
    fragments.append(original_review)

    # Combine and trim
    full_text = "\n\n".join(fragments)
    return trim_for_prompt(full_text, max_chars)


REMEDIATION_ROLE_PROMPT = """You are running a bounded review-remediation loop.

Remediate the valid actionable findings to high quality while respecting the
repository's instructions and engineering principles.

Rules:
- Keep the patch focused on the review findings.
- Preserve existing user changes; do not revert unrelated work.
- Maintain the repository's Code + Documentation + Tests atomic-unit rule.
- Add or update tests for behavior changes.
- Run the most relevant verification commands before finishing.
- If a finding is invalid or impossible to fix safely, explain that in your final response.
"""


def load_fragment(cwd: Path, name: str) -> str | None:
    # Try common extensions and naming patterns
    candidates = [
        cwd / f"{name}.md",
        cwd / f"{name}.txt",
        cwd / f"{name}-v1.1.md", # Specific for engineering-principles-v1.1.md
    ]
    
    # Special case for engineering-principles as it's a core concept
    if name == "engineering-principles":
        candidates.insert(0, cwd / "engineering-principles-v1.1.md")

    for cand in candidates:
        if cand.is_file():
            try:
                return cand.read_text(encoding="utf-8")
            except OSError:
                pass
    return None


def trim_for_prompt(text: str, max_chars: int) -> str:
    if max_chars < 1:
        raise ValueError("max prompt characters must be positive")
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    marker = f"\n\n[... omitted {omitted} characters to stay under prompt limit ...]\n\n"
    if len(marker) >= max_chars:
        return marker[:max_chars]
    keep_total = max_chars - len(marker)
    keep_head = keep_total // 2
    keep_tail = keep_total - keep_head
    return (
        text[:keep_head]
        + marker
        + text[-keep_tail:]
    )


def compute_prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
