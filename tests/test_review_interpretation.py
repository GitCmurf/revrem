"""Tests for core/review_interpretation.py (REVREM-TASK-003 B1a).

Imports are taken directly from the new canonical home, NOT via cli, to
prove the module is independently importable and dependency-free.
"""

from __future__ import annotations

import pytest

from code_review_loop.core.review_interpretation import (
    actionable_review_output,
    detect_review_status,
    extract_finding_blocks,
    extract_finding_summaries,
    extract_review_summary,
    has_affirmative_issue_prose,
    strip_finding_priority,
)

# ---------------------------------------------------------------------------
# Corpus — 8 representative review outputs tagged with expected status.
# Each entry: (label, output_text, expected_status)
# Provenance comments indicate where the pattern comes from.
# ---------------------------------------------------------------------------

CORPUS: list[tuple[str, str, str]] = [
    # 1. Explicit REVIEW_STATUS: clear marker (from Codex review output ca. 2025-03)
    (
        "explicit_clear_status_line",
        "The patch looks correct.\nREVIEW_STATUS: clear\n",
        "clear",
    ),
    # 2. Explicit REVIEW_STATUS: findings marker (from Codex review output ca. 2025-03)
    (
        "explicit_findings_status_line",
        "There are issues.\nREVIEW_STATUS: findings\n",
        "findings",
    ),
    # 3. Structured JSON with findings list populated (from Codex structured JSON ca. 2025-04)
    (
        "structured_json_with_findings",
        '{"findings": [{"priority": "P1", "summary": "null pointer"}]}',
        "findings",
    ),
    # 4. Structured JSON with empty findings list (from Codex structured JSON ca. 2025-04)
    (
        "structured_json_empty_findings",
        '{"findings": [], "overall_correctness": "patch is correct"}',
        "clear",
    ),
    # 5. "No findings." exact line (from canonical Codex clear output ca. 2025-03)
    (
        "no_findings_exact_line",
        "No findings.\n",
        "clear",
    ),
    # 6. Negated clear statement in prose (from NLP heuristic coverage ca. 2025-05)
    (
        "negated_clear_prose",
        "I did not find any discrete, actionable bugs in the diff.",
        "clear",
    ),
    # 7. Affirmative issue prose with finding bullet (from typical Codex findings output ca. 2025-03)
    (
        "finding_bullet_p1",
        "Full review comments:\n\n- [P1] Fix the null dereference — src/foo.py:42\n",
        "findings",
    ),
    # 8. Ambiguous / unknown — no strong signal either way (from edge-case corpus ca. 2025-05)
    (
        "ambiguous_no_signal",
        "This review has a detailed discussion.",
        "unknown",
    ),
]


@pytest.mark.parametrize("label,output,expected", CORPUS, ids=[c[0] for c in CORPUS])
def test_detect_review_status_corpus(label: str, output: str, expected: str) -> None:
    assert detect_review_status(output) == expected


# ---------------------------------------------------------------------------
# Ported from test_cli.py — verify parity at the canonical import location
# ---------------------------------------------------------------------------


def test_detect_review_status_prefers_explicit_status_line() -> None:
    assert detect_review_status("Looks good\nREVIEW_STATUS: clear\n") == "clear"
    assert detect_review_status("One blocker\nREVIEW_STATUS: findings\n") == "findings"


def test_detect_review_status_treats_ambiguous_output_as_unknown() -> None:
    assert detect_review_status("This review has a detailed discussion.") == "unknown"


def test_detect_review_status_accepts_exact_clear_review_lines() -> None:
    assert detect_review_status("No findings.\n") == "clear"
    assert detect_review_status("summary\nNo actionable findings\n") == "clear"
    assert (
        detect_review_status(
            "No discrete correctness issues were found in the diff. The added "
            "wizard path and tests appear internally consistent."
        )
        == "clear"
    )
    assert (
        detect_review_status("I did not find any discrete, actionable bugs in the diff.") == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any discrete introduced bugs that should block the patch. "
            "The repository's dev-check suite passes locally."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any introduced, actionable correctness issues in "
            "the changed code. A local full pytest run had one subprocess import "
            "failure in an existing test/tool path, but it does not appear tied "
            "to the diff under review."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any discrete, actionable bugs in the diff relative "
            "to the requested base commit. CodeRabbit also completed with zero findings."
        )
        == "clear"
    )
    assert detect_review_status("This would warrant an inline finding.") == "unknown"


def test_detect_review_status_does_not_generalize_negated_clear_with_findings() -> None:
    assert (
        detect_review_status(
            "I did not identify any broad design problem.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix the actual bug — src/example.py:10\n"
        )
        == "findings"
    )


def test_detect_review_status_requires_explicit_status_line() -> None:
    assert detect_review_status("no findings about style, but several about logic") == "unknown"
    assert detect_review_status("review is clear of syntax errors but not semantic") == "unknown"
    assert detect_review_status("") == "unknown"


# ---------------------------------------------------------------------------
# has_affirmative_issue_prose (UNRELATED_FAILURE_RE over-filter regression)
# ---------------------------------------------------------------------------


def test_has_affirmative_issue_prose_keeps_real_finding_after_unrelated_clause() -> None:
    """A sentence that mentions BOTH a real bug and an unrelated
    environment issue must still be reported as affirmative issue prose.
    The previous whole-sentence skip over-filtered such sentences.
    """
    output = "I found a real bug here, and an unrelated environment issue I will set aside."
    assert has_affirmative_issue_prose(output) is True


def test_has_affirmative_issue_prose_still_drops_purely_unrelated_clause() -> None:
    output = "There is a pre-existing environment issue I will set aside."
    assert has_affirmative_issue_prose(output) is False


def test_has_affirmative_issue_prose_keeps_bug_in_separate_sentence_from_unrelated() -> None:
    output = (
        "There is an unrelated environment issue I will set aside.\n"
        "The diff still introduces a real bug in the retry path."
    )
    assert has_affirmative_issue_prose(output) is True


# ---------------------------------------------------------------------------
# actionable_review_output
# ---------------------------------------------------------------------------


def test_actionable_review_output_drops_verbose_stderr_transcript() -> None:
    output = "Full review comments:\n\n- [P1] Fix the bug\n\n[stderr]\n" + (
        "diff --git a/x b/x\n" * 100
    )
    assert actionable_review_output(output) == "Full review comments:\n\n- [P1] Fix the bug"


def test_actionable_review_output_falls_back_to_full_output_when_no_stderr() -> None:
    output = "No findings.\n"
    assert actionable_review_output(output) == "No findings."


# ---------------------------------------------------------------------------
# extract_finding_summaries
# ---------------------------------------------------------------------------


def test_extract_finding_summaries_limits_codex_findings() -> None:
    output = """Full review comments:

- [P1] First bug — src/a.py:1
  Detail.
- [P2] Second bug — src/b.py:2
- [P3] Third bug — src/c.py:3
"""
    assert extract_finding_summaries(output, limit=2) == [
        "[P1] First bug — src/a.py:1",
        "[P2] Second bug — src/b.py:2",
    ]


def test_extract_finding_summaries_returns_empty_for_clear_output() -> None:
    assert extract_finding_summaries("REVIEW_STATUS: clear\n") == []


# ---------------------------------------------------------------------------
# extract_finding_blocks
# ---------------------------------------------------------------------------


def test_extract_finding_blocks_includes_short_detail() -> None:
    output = """Full review comments:

- [P1] First bug — src/a.py:1
  The first detail line.
  The second detail line.
  The third detail line.
- [P2] Second bug — src/b.py:2
  Another detail.
"""
    assert extract_finding_blocks(output, limit=2, detail_lines=2) == [
        [
            "[P1] First bug — src/a.py:1",
            "The first detail line.",
            "The second detail line.",
        ],
        ["[P2] Second bug — src/b.py:2", "Another detail."],
    ]


def test_extract_finding_blocks_returns_empty_list_for_no_findings() -> None:
    assert extract_finding_blocks("No findings.\n") == []


# ---------------------------------------------------------------------------
# extract_review_summary
# ---------------------------------------------------------------------------


def test_extract_review_summary_uses_leading_review_prose() -> None:
    output = """The loop can omit the only review transcript path in a failure summary.

Full review comments:

- [P2] Prefix iteration review artifact labels — scripts/loop.py:1
  Detail.
"""
    assert (
        extract_review_summary(output)
        == "The loop can omit the only review transcript path in a failure summary."
    )


def test_extract_review_summary_returns_empty_for_blank_output() -> None:
    assert extract_review_summary("") == ""
    assert extract_review_summary("   ") == ""


# ---------------------------------------------------------------------------
# strip_finding_priority
# ---------------------------------------------------------------------------


def test_strip_finding_priority_extracts_priority_tag() -> None:
    assert strip_finding_priority("[P1] Fix the bug") == ("[P1]", "Fix the bug")
    assert strip_finding_priority("[P0] Critical issue") == ("[P0]", "Critical issue")


def test_strip_finding_priority_returns_empty_tag_for_no_match() -> None:
    assert strip_finding_priority("No priority tag here") == ("", "No priority tag here")
    assert strip_finding_priority("") == ("", "")
