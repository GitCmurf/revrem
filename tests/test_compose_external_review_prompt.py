"""Tests for ``compose_external_review_prompt`` (RevRem remediation: review.py).

Pins the contract for the external review prompt composer:

* the returned ``provider_context`` is a substring of the returned ``prompt``;
* the second-pass trim (when the first composition still exceeds the input
  cap) preserves that invariant;
* truncated and non-truncated branches report the right shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop.adapters import phase_support
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


@pytest.mark.parametrize(
    "external_review_input_chars",
    [60, 80, 100, 120, 150],
)
def test_compose_external_review_prompt_provider_context_matches_head_tail_anchors(
    external_review_input_chars: int,
) -> None:
    """Pin exact head/tail boundaries in the surfaced provider_context.

    With aggressive input caps the second-pass ``trim_for_prompt`` can
    partially clip the head and/or tail strings, or replace the tail
    entirely with the omission marker. The recovered ``provider_context``
    must sit between the actual remaining head and tail anchors in the
    trimmed prompt, not be re-sliced with the *original* head/tail
    lengths (which can drift after a second trim).
    """
    config = _config(external_review_input_chars=external_review_input_chars)
    review_context = ("X" * 50 + "Y" * 50) * 5

    result = compose_external_review_prompt(config, review_context)

    prompt_head = f"{phase_support.DEFAULT_REVIEW_PROMPT}\n\n"
    prompt_tail = f"\n\n{EXTERNAL_REVIEW_PROMPT_TAIL}"
    assert len(result.prompt) <= external_review_input_chars
    if result.provider_context:
        head_index = result.prompt.index(result.provider_context)
        tail_index = head_index + len(result.provider_context)
        actual_head_len = head_index
        actual_tail_len = len(result.prompt) - tail_index
        assert actual_head_len <= len(prompt_head)
        assert actual_tail_len <= len(prompt_tail)
        assert result.prompt[:actual_head_len] == prompt_head[:actual_head_len], (
            "head anchor in prompt must match the leading slice of prompt_head"
        )
        if actual_tail_len > 0:
            assert result.prompt[-actual_tail_len:] == prompt_tail[-actual_tail_len:], (
                "tail anchor in prompt must match the trailing slice of prompt_tail"
            )
