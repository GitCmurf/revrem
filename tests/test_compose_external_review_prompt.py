"""Tests for ``compose_external_review_prompt`` (RevRem remediation: review.py).

Pins the contract for the external review prompt composer:

* the returned ``provider_context`` is a substring of the returned ``prompt``;
* the second-pass trim (when the first composition still exceeds the input
  cap) preserves that invariant;
* truncated and non-truncated branches report the right shape.
"""

from __future__ import annotations

from pathlib import Path

from code_review_loop.adapters.review import (
    EXTERNAL_REVIEW_PROMPT_TAIL,
    compose_external_review_prompt,
)
from code_review_loop.config import LoopConfig


def _config(external_review_input_chars: int) -> LoopConfig:
    return LoopConfig(
        base="main",
        max_iterations=1,
        cwd=Path("/tmp"),
        artifact_dir=Path("/tmp/artifacts"),
        external_review_input_chars=external_review_input_chars,
    )


def test_compose_external_review_prompt_keeps_context_within_cap() -> None:
    config = _config(external_review_input_chars=10_000)
    review_context = "context body\n" * 200

    result = compose_external_review_prompt(config, review_context)

    assert result.context_chars == len(review_context)
    assert result.input_cap_chars == 10_000
    assert len(result.prompt) <= 10_000
    assert result.provider_context in result.prompt


def test_compose_external_review_prompt_truncates_long_context() -> None:
    config = _config(external_review_input_chars=400)
    review_context = "context body\n" * 200

    result = compose_external_review_prompt(config, review_context)

    assert result.truncated is True
    assert len(result.prompt) <= 400
    assert result.provider_context in result.prompt


def test_compose_external_review_prompt_passes_through_short_context() -> None:
    config = _config(external_review_input_chars=200_000)
    review_context = "small context\n"

    result = compose_external_review_prompt(config, review_context)

    assert result.truncated is False
    assert result.provider_context in result.prompt
    assert "small context" in result.prompt


def test_compose_external_review_prompt_second_pass_preserves_substring_invariant() -> None:
    """Force the second-pass branch by making the prompt head/tail dominate.

    With a tiny cap, the first trim keeps a small context window; the
    concatenated prompt + head + tail still exceeds the cap, so the second
    trim fires. The bug pinned by this test was that the returned
    ``provider_context`` was the pre-second-pass ``trimmed_context`` and
    no longer a substring of the returned ``prompt``.
    """
    config = _config(external_review_input_chars=120)
    review_context = ("X" * 40 + "Y" * 40) * 5

    result = compose_external_review_prompt(config, review_context)

    assert len(result.prompt) <= 120
    assert result.provider_context in result.prompt, (
        "provider_context must remain a substring of prompt across both trims"
    )


def test_compose_external_review_prompt_keeps_head_and_tail_anchors() -> None:
    config = _config(external_review_input_chars=10_000)
    review_context = "context body\n" * 200

    result = compose_external_review_prompt(config, review_context)

    assert "Review the current repository changes" in result.prompt
    assert EXTERNAL_REVIEW_PROMPT_TAIL.strip() in result.prompt
