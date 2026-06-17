"""NLP heuristics for classifying Codex review output (REVREM-TASK-003 B1a).

This module is the canonical home for all regex constants and pure functions
that interpret the natural-language (and structured JSON) output of review
harnesses.  It is intentionally dependency-free — only stdlib is imported —
so the logic is testable in isolation and can be consumed by any layer without
pulling in edge concerns (LoopConfig, terminal I/O, subprocesses, etc.).

Do NOT import from cli.py, argparse, or any non-stdlib module.
"""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

STATUS_RE = re.compile(r"^\s*REVIEW_STATUS:\s*(clear|findings)\s*$", re.IGNORECASE | re.MULTILINE)
CODEX_FINDING_RE = re.compile(r"^\s*-\s*\[P[0-3]\]\s+", re.MULTILINE)
CODEX_FINDING_LINE_RE = re.compile(r"^\s*-\s*(\[P[0-3]\]\s+.+)$")
REVIEW_COMMENTS_HEADING_RE = re.compile(
    r"^\s*(full\s+)?review comments?:\s*$",
    re.IGNORECASE | re.MULTILINE,
)

NEGATED_CLEAR_REVIEW_STATEMENT_RE = re.compile(
    r"(?:^|[.!?,;]\s+|,\s+and\s+|and\s+)(?:i\s+)?did not (?:identify|find) "
    r"(?:any(?: discrete(?: introduced)?)?|a discrete(?: introduced)?)\b"
    r"[^.!?]*(?:issue|issues|bug|bugs|defect|defects|regression|regressions|finding|findings|correctness|security|maintainability)"
)

AFFIRMATIVE_ISSUE_WORD_RE = re.compile(
    r"\b(?:bug|bugs|issue|issues|regression|regressions|defect|defects|problem|problems|"
    r"failure|failures|finding|findings)\b",
    re.IGNORECASE,
)
NON_CORRECTNESS_ISSUE_RE = re.compile(
    r"\b(?:"
    r"vulnerab\w+"
    r"|insecure(?:\s+\w+){0,3}"
    r"|unsafe(?:\s+\w+){0,3}"
    r"|exploit(?:s|ed|ing|ation|able|ability)?"
    r"|leak(?:s|age|ed|ing)?"
    r"|expos(?:e|es|ed|ing|ure)"
    r"|security(?:\s+\w+){0,4}\s+(?:issue|issues|problem|problems|risk|risks|concern|concerns|"
    r"vulnerab\w+|flaw|flaws|debt)"
    r"|maintainabil(?:ity|y)(?:\s+\w+){0,4}\s+(?:issue|issues|problem|problems|risk|risks|"
    r"concern|concerns|debt|flaw|flaws)"
    r"|hard to maintain"
    r"|difficult to maintain"
    r"|maintenance burden"
    r")\b",
    re.IGNORECASE,
)
NEGATED_NON_CORRECTNESS_ISSUE_RE = re.compile(
    r"\b(?:"
    r"(?:(?:not|is\s+not|isn't|was\s+not|wasn't|are\s+not|aren't|were\s+not|weren't|"
    r"no|without(?:\s+any)?)\s+(?:an?\s+)?)"
    r"|(?:(?:do|does|did)\s+not|don't|doesn't|didn't)\s+"
    r"(?:introduce|create)\s+(?:an?\s+|any\s+)?"
    r")(?:"
    r"vulnerab\w+"
    r"|insecure(?:\s+\w+){0,3}"
    r"|unsafe(?:\s+\w+){0,3}"
    r"|exploit(?:s|ed|ing|ation|able|ability)?"
    r"|leak(?:s|age|ed|ing)?"
    r"|expos(?:e|es|ed|ing|ure)"
    r"|security(?:\s+\w+){0,4}\s+(?:issue|issues|problem|problems|risk|risks|concern|concerns|"
    r"vulnerab\w+|flaw|flaws|debt)"
    r"|maintainabil(?:ity|y)(?:\s+\w+){0,4}\s+(?:issue|issues|problem|problems|risk|risks|"
    r"concern|concerns|debt|flaw|flaws)"
    r"|hard to maintain"
    r"|difficult to maintain"
    r"|maintenance burden"
    r")\b",
    re.IGNORECASE,
)
STRUCTURED_EMPTY_FINDINGS_RE = re.compile(
    r'(?<!\w)["\']?findings["\']?\s*:\s*\[\s*\](?!\w)',
    re.IGNORECASE,
)
TOOL_DENIAL_CONTROL_RE = re.compile(
    r"^(?:"
    r"error executing tool\b.*(?:tool execution (?:denied|requires user confirmation)|denied by policy|requires user confirmation)"
    r"|tool execution (?:denied|requires user confirmation)\b"
    r"|denied by policy\b"
    r"|requires user confirmation\b"
    r")",
    re.IGNORECASE,
)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
UNRELATED_FAILURE_RE = re.compile(
    r"\b(?:failure|failures|issue|issues|problem|problems)\b"
    r"[^.!?]*\b(?:environment|pyth?onpath|local environment|unchanged|unrelated|"
    r"not caused by|not introduced by|not a regression|outside the diff|not from this patch|"
    r"not tied to|does not appear tied to|doesn't appear tied to)\b"
    r"|"
    r"\b(?:environment|pyth?onpath|local environment|unchanged|unrelated|"
    r"not caused by|not introduced by|not a regression|outside the diff|not from this patch|"
    r"not tied to|does not appear tied to|doesn't appear tied to)\b"
    r"[^.!?]*\b(?:failure|failures|issue|issues|problem|problems)\b",
    re.IGNORECASE,
)
UNRELATED_KEYWORD_RE = re.compile(
    r"\b(?:environment|pyth?onpath|local environment|unchanged|unrelated|"
    r"not caused by|not introduced by|not a regression|outside the diff|not from this patch|"
    r"not tied to|does not appear tied to|doesn't appear tied to)\b",
    re.IGNORECASE,
)
_UNRELATED_PROXIMITY_CHARS = 80

NEGATED_ISSUE_PREFIX_RE = r"(?:clear|discrete|actionable|introduced|known|new|obvious|blocking|material|major|serious|outstanding|significant|additional|further|remaining|open|critical|severe|real|actual|genuine|substantive|meaningful|correctness|security|maintainability)"
NEGATED_ISSUE_PREFIX_SEPARATOR_RE = r"[\s,;:-]+(?:(?:and|or)\s+)?"
NEGATED_ISSUE_PREFIX_CHAIN_RE = (
    rf"{NEGATED_ISSUE_PREFIX_RE}(?:{NEGATED_ISSUE_PREFIX_SEPARATOR_RE}"
    rf"{NEGATED_ISSUE_PREFIX_RE})*"
)
NEGATED_ISSUE_WORD_RE = r"(?:bug|bugs|issue|issues|regression|regressions|defect|defects|problem|problems|failure|failures|finding|findings)"
NEGATED_ISSUE_PROSE_RE = re.compile(
    rf"\b(?:"
    rf"no(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|zero(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|without(?:\s+any)?(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|without\s+revealing(?:\s+any)?(?:\s+{NEGATED_ISSUE_PREFIX_CHAIN_RE})?\s+{NEGATED_ISSUE_WORD_RE}\b"
    rf"|(?:did|does|do)\s+not\s+"
    rf"(?:find|identify|detect|see|spot|surface|observe|notice)\s+"
    rf"(?:any\s+)?(?:{NEGATED_ISSUE_PREFIX_CHAIN_RE}\s+)?{NEGATED_ISSUE_WORD_RE}\b"
    rf"|(?:didn't|doesn't|don't|cannot|can't)\s+"
    rf"(?:find|identify|detect|see|spot|surface|observe|notice)\s+"
    rf"(?:any\s+)?(?:{NEGATED_ISSUE_PREFIX_CHAIN_RE}\s+)?{NEGATED_ISSUE_WORD_RE}\b"
    rf")",
    re.IGNORECASE,
)
CONTRASTIVE_CLAUSE_RE = re.compile(
    r"\b(?:but|however|though|although|yet|nevertheless|nonetheless|still)\b",
    re.IGNORECASE,
)

CLEAR_PHRASES = (
    # Keep only negated forms here. Broad phrases like "warrant an inline finding"
    # can appear in positive review prose and must not force a clear status.
    "did not find any discrete, actionable bugs",
    "did not find any discrete, actionable correctness issues",
    "did not find a discrete introduced bug",
    "did not find any discrete introduced bug",
    "did not find any actionable bugs",
    "did not find any actionable bugs introduced by the reviewed diff",
    "did not find any actionable bugs introduced by the diff",
    "did not identify a discrete introduced correctness, security, or maintainability issue that should block the patch",
    "did not identify any discrete introduced bugs that should block the patch",
    "did not identify any discrete introduced bugs that would block the patch",
    "did not identify any actionable correctness, security, or maintainability issues",
    "did not identify any introduced, actionable correctness issues",
    "did not identify any introduced correctness, security, or maintainability issues",
    "did not identify any introduced correctness, security, or maintainability issues that warrant an inline finding",
    "no actionable correctness, security, or maintainability issues were found",
    "no actionable correctness, security, or maintainability issues were identified",
    "without revealing any discrete correctness issue",
    "no discrete, actionable bugs",
    "no discrete, actionable correctness issues were found",
    "no discrete correctness issues were found",
    "no actionable bugs",
    "without any clear regressions or actionable bugs",
    "without any clear regressions or actionable",
)

PROMPTED_REVIEW_HARNESSES = frozenset({"claude", "gemini", "opencode", "kilo"})
STDERR_MARKER = "[stderr]\n"

# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------


def _split_review_and_stderr(output: str) -> tuple[str, str]:
    stripped = output.strip()
    if stripped.startswith(STDERR_MARKER):
        return "", stripped[len(STDERR_MARKER) :].strip()
    review_text, sep, stderr_text = stripped.partition(f"\n{STDERR_MARKER}")
    if sep:
        return review_text.strip(), stderr_text.strip()
    return stripped, ""


def actionable_review_output(output: str) -> str:
    """Keep the review's actionable comments, not the verbose tool transcript."""
    review_text, _stderr_text = _split_review_and_stderr(output)
    return review_text


def stderr_review_output(output: str) -> str:
    """Return provider stderr/control text from a combined review artifact."""
    _review_text, stderr_text = _split_review_and_stderr(output)
    return stderr_text


def tool_denial_evidence(stderr_output: str) -> str | None:
    """Return provider-control denial evidence from stderr, if present.

    External harnesses such as OpenCode write shell transcripts to stderr. Those
    transcripts can include reviewed diff lines and test fixture strings that
    mention "denied by policy" without representing a provider denial. Treat
    only denial-looking lines that start as provider-control errors as evidence.
    """
    for raw_line in stderr_output.splitlines():
        line = ANSI_ESCAPE_RE.sub("", raw_line).strip()
        if not line:
            continue
        if TOOL_DENIAL_CONTROL_RE.search(line):
            return line[:240]
    return None


# ---------------------------------------------------------------------------
# Prose-level helpers
# ---------------------------------------------------------------------------


def iter_review_prose_sentences(output: str):
    """Yield prose fragments, treating line breaks as hard boundaries.

    Review summaries are often wrapped onto new lines without terminal
    punctuation, so line boundaries must split before sentence heuristics are
    applied. That keeps a clear statement on one line from suppressing an issue
    reported on the next line.
    """

    for paragraph in re.split(r"\n+", output.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            sentence = sentence.strip()
            if sentence:
                yield sentence


def has_negated_clear_review_statement(normalized: str) -> bool:
    return NEGATED_CLEAR_REVIEW_STATEMENT_RE.search(normalized) is not None


def has_affirmative_contrastive_issue_clause(sentence: str) -> bool:
    """Return True when a contrastive clause still reports an issue.

    A sentence can negate issues in one clause and then introduce a real
    finding after a contrastive marker such as "but" or "however". The
    negation should not suppress the later clause.
    """

    for match in CONTRASTIVE_CLAUSE_RE.finditer(sentence):
        suffix = sentence[match.end() :]
        if not suffix:
            continue
        if not AFFIRMATIVE_ISSUE_WORD_RE.search(suffix):
            continue
        if NEGATED_ISSUE_PROSE_RE.search(suffix):
            continue
        return True
    return False


def has_affirmative_issue_prose(output: str) -> bool:
    for sentence in iter_review_prose_sentences(output):
        if not sentence:
            continue
        normalized_sentence = sentence.lower()
        if STRUCTURED_EMPTY_FINDINGS_RE.search(sentence):
            # Codex-style structured output often includes a literal empty findings
            # array alongside a clear explanation. Do not treat that field name as
            # affirmative issue prose.
            continue
        if not AFFIRMATIVE_ISSUE_WORD_RE.search(sentence):
            continue
        if UNRELATED_FAILURE_RE.search(sentence):
            if not _sentence_introduces_unrelated_as_disclaimer(sentence):
                # The unrelated span is not a separate disclaimer; the
                # whole sentence is describing an issue that is itself
                # tagged as unrelated. Drop it.
                continue
            stripped = _strip_unrelated_failure_spans(sentence)
            if not AFFIRMATIVE_ISSUE_WORD_RE.search(stripped):
                continue
            sentence = stripped
            normalized_sentence = sentence.lower()
        if has_affirmative_contrastive_issue_clause(sentence):
            return True
        if has_negated_clear_review_statement(normalized_sentence):
            continue
        if NEGATED_NON_CORRECTNESS_ISSUE_RE.search(sentence):
            continue
        if NEGATED_ISSUE_PROSE_RE.search(sentence):
            continue
        return True
    return False


def has_affirmative_non_correctness_contrastive_clause(sentence: str) -> bool:
    for match in CONTRASTIVE_CLAUSE_RE.finditer(sentence):
        suffix = sentence[match.end() :]
        if not suffix:
            continue
        if not NON_CORRECTNESS_ISSUE_RE.search(suffix):
            continue
        if NEGATED_NON_CORRECTNESS_ISSUE_RE.search(suffix):
            continue
        return True
    return False


def has_non_correctness_issue_prose(output: str) -> bool:
    """Return True when the prose contains a likely security/maintainability finding.

    Correctness-only clear wording can be valid for a review that still reports
    non-correctness issues. This helper catches the common non-correctness
    finding language that does not always include the generic issue keywords.
    """

    for sentence in iter_review_prose_sentences(output):
        if not sentence:
            continue
        normalized_sentence = sentence.lower()
        if NON_CORRECTNESS_ISSUE_RE.search(sentence):
            if has_affirmative_non_correctness_contrastive_clause(sentence):
                return True
            if has_negated_clear_review_statement(normalized_sentence):
                continue
            if NEGATED_NON_CORRECTNESS_ISSUE_RE.search(normalized_sentence):
                continue
            if NEGATED_ISSUE_PROSE_RE.search(normalized_sentence):
                continue
            return True
    return False


def _strip_unrelated_failure_spans(sentence: str) -> str:
    """Remove the spans matched by ``UNRELATED_FAILURE_RE`` from a sentence.

    The regex matches clauses that explicitly tag an issue as "unrelated",
    "not from this patch", etc. A sentence may mention BOTH an unrelated
    environmental issue and a real finding; we only want to drop the
    explicitly unrelated clause and keep the rest for downstream negation
    checks. Collapsed whitespace is normalised so the remainder re-evaluates
    cleanly.
    """
    parts: list[str] = []
    last_end = 0
    for match in UNRELATED_FAILURE_RE.finditer(sentence):
        parts.append(sentence[last_end : match.start()])
        last_end = match.end()
    parts.append(sentence[last_end:])
    collapsed = " ".join(" ".join(part.split()) for part in parts if part.strip())
    return collapsed.strip()


_UNRELATED_DISCLAIMER_INTRO_RE = re.compile(
    r"\b(?:and|but|however|though|although|yet|while|though|whereas)\b",
    re.IGNORECASE,
)


def _sentence_introduces_unrelated_as_disclaimer(sentence: str) -> bool:
    """Return True when the sentence joins a real-issue clause with an
    unrelated-issue clause via a conjunction such as "and" or "but".

    When a sentence reads "I found a real bug, and an unrelated
    environment issue I will set aside", the unrelated span is a
    disclaimer around the issue. Stripping the span should keep the
    real issue in the remainder.

    For sentences that read "The diff has a failure in an unchanged
    test path that appears to be a local environment issue, not a
    regression", the whole sentence is describing the unrelated
    failure. There is no conjunction introducing the unrelated span
    as a parallel clause; the issue IS the unrelated thing.
    """
    if not _UNRELATED_DISCLAIMER_INTRO_RE.search(sentence):
        return False
    first_issue = AFFIRMATIVE_ISSUE_WORD_RE.search(sentence)
    first_conjunction = _UNRELATED_DISCLAIMER_INTRO_RE.search(sentence)
    if first_issue is None or first_conjunction is None:
        return False
    return first_issue.start() < first_conjunction.start()


def structured_review_status(output: str) -> str | None:
    """Classify Codex structured JSON review output when it exposes findings."""
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    findings = parsed.get("findings")
    if isinstance(findings, list):
        return "findings" if findings else "clear"
    return None


# ---------------------------------------------------------------------------
# Top-level classifier
# ---------------------------------------------------------------------------


def detect_review_status(output: str, *, harness: str = "codex") -> str:
    """Return clear/findings/unknown for review output.

    Codex native review is classified with a conservative prose corpus because
    RevRem does not control that prompt. Prompted external review harnesses are
    held to the explicit/structured status contract that RevRem supplies.
    """
    actionable_output = actionable_review_output(output)
    if harness in PROMPTED_REVIEW_HARNESSES:
        return _detect_prompted_review_status_from_actionable(actionable_output)
    return _detect_review_status_from_actionable(actionable_output)


def _detect_prompted_review_status_from_actionable(actionable_output: str) -> str:
    match = STATUS_RE.search(actionable_output)
    if match:
        return match.group(1).lower()

    structured_status = structured_review_status(actionable_output)
    if structured_status is not None:
        return structured_status

    if CODEX_FINDING_RE.search(actionable_output):
        return "findings"
    return "unknown"


def _detect_review_status_from_actionable(actionable_output: str) -> str:
    match = STATUS_RE.search(actionable_output)
    if match:
        return match.group(1).lower()

    structured_status = structured_review_status(actionable_output)
    if structured_status is not None:
        return structured_status

    if CODEX_FINDING_RE.search(actionable_output):
        return "findings"

    normalized = actionable_output.lower()
    finding_markers = (
        "review comment:",
        "review comments:",
        "full review comments:",
    )
    if any(marker in normalized for marker in finding_markers):
        return "findings"

    normalized_lines = [line.strip().lower() for line in actionable_output.splitlines()]
    clear_lines = {
        "no findings.",
        "no findings",
        "no issues found.",
        "no issues found",
        "no actionable findings.",
        "no actionable findings",
    }
    if any(line in clear_lines for line in normalized_lines):
        return "clear"
    if has_negated_clear_review_statement(normalized) and not has_affirmative_issue_prose(
        actionable_output
    ) and not has_non_correctness_issue_prose(actionable_output):
        return "clear"
    if any(phrase in normalized for phrase in CLEAR_PHRASES) and not has_affirmative_issue_prose(
        actionable_output
    ) and not has_non_correctness_issue_prose(actionable_output):
        return "clear"
    return "unknown"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def review_status_diagnostics(output: str, *, harness: str = "codex") -> dict[str, object]:
    """Return compact, targeted diagnostics for review-status classification."""
    actionable_output = actionable_review_output(output)
    stderr_output = stderr_review_output(output)
    denial_evidence = tool_denial_evidence(stderr_output)
    stderr_present = bool(stderr_output)
    explicit_status = STATUS_RE.search(actionable_output)
    finding_lines = CODEX_FINDING_RE.findall(actionable_output)
    normalized = actionable_output.lower()
    matched_clear_phrase = next(
        (phrase for phrase in CLEAR_PHRASES if phrase in normalized),
        None,
    )
    clear_phrase_present = matched_clear_phrase is not None or has_negated_clear_review_statement(
        normalized
    )
    structured_status = structured_review_status(actionable_output)
    affirmative_issue_prose = has_affirmative_issue_prose(actionable_output)
    non_correctness_issue_prose = has_non_correctness_issue_prose(actionable_output)
    if explicit_status:
        status_source = "explicit_status"
    elif structured_status is not None:
        status_source = "structured_findings"
    elif finding_lines:
        status_source = "codex_finding_bullet"
    elif (
        harness not in PROMPTED_REVIEW_HARNESSES
        and any(
            marker in normalized
            for marker in (
                "review comment:",
                "review comments:",
                "full review comments:",
            )
        )
    ):
        status_source = "finding_markers"
    elif (
        harness not in PROMPTED_REVIEW_HARNESSES
        and any(
            line
            in {
                "no findings.",
                "no findings",
                "no issues found.",
                "no issues found",
                "no actionable findings.",
                "no actionable findings",
            }
            for line in [raw_line.strip().lower() for raw_line in actionable_output.splitlines()]
        )
    ):
        status_source = "clear_lines"
    elif (
        harness not in PROMPTED_REVIEW_HARNESSES
        and clear_phrase_present
        and not affirmative_issue_prose
        and not non_correctness_issue_prose
    ):
        status_source = "codex_clear_prose"
    else:
        status_source = "none"
    status = detect_review_status(output, harness=harness)
    clear_phrase_used = status_source == "codex_clear_prose"
    ignored_clear_phrase_reason = None
    if clear_phrase_present and not clear_phrase_used:
        if status_source in {
            "explicit_status",
            "structured_findings",
            "codex_finding_bullet",
            "finding_markers",
        }:
            ignored_clear_phrase_reason = "finding_signal_won"
        elif non_correctness_issue_prose:
            ignored_clear_phrase_reason = "non_correctness_issue_prose"
        elif affirmative_issue_prose:
            ignored_clear_phrase_reason = "affirmative_issue_prose"
        elif harness in PROMPTED_REVIEW_HARNESSES:
            ignored_clear_phrase_reason = "prompted_harness_requires_explicit_status"
        elif status_source == "clear_lines":
            ignored_clear_phrase_reason = "clear_line_won"
        else:
            ignored_clear_phrase_reason = "not_status_deciding_signal"
    return {
        "status": status,
        "status_source": status_source,
        "status_deciding_signal": status_source,
        "actionable_chars": len(actionable_output),
        "stderr_present": stderr_present,
        "explicit_status": (explicit_status.group(1).lower() if explicit_status else None),
        "finding_line_count": len(finding_lines),
        "clear_phrase_present": clear_phrase_present,
        "clear_phrase_used": clear_phrase_used,
        "ignored_clear_phrase_reason": ignored_clear_phrase_reason,
        "matched_clear_phrase": matched_clear_phrase,
        "harness": harness,
        "explicit_status_required": harness in PROMPTED_REVIEW_HARNESSES,
        "tool_denial_present": denial_evidence is not None,
        "tool_denial_source": "stderr_control" if denial_evidence else None,
        "tool_denial_evidence": denial_evidence,
    }


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def extract_finding_summaries(output: str, limit: int = 5) -> list[str]:
    summaries: list[str] = []
    for line in actionable_review_output(output).splitlines():
        match = CODEX_FINDING_LINE_RE.match(line)
        if not match:
            continue
        summaries.append(match.group(1).strip())
        if len(summaries) >= limit:
            break
    return summaries


def extract_finding_blocks(output: str, limit: int = 5, detail_lines: int = 2) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    current_details = 0

    for raw_line in actionable_review_output(output).splitlines():
        match = CODEX_FINDING_LINE_RE.match(raw_line)
        if match:
            if current:
                blocks.append(current)
                if len(blocks) >= limit:
                    return blocks
            current = [match.group(1).strip()]
            current_details = 0
            continue

        if current is None or current_details >= detail_lines:
            continue

        stripped = raw_line.strip()
        if not stripped:
            continue
        current.append(stripped)
        current_details += 1

    if current and len(blocks) < limit:
        blocks.append(current)
    return blocks


def extract_review_summary(output: str) -> str:
    """Return the review's leading prose summary, excluding finding bullets."""
    text = actionable_review_output(output).strip()
    if not text:
        return ""
    text = REVIEW_COMMENTS_HEADING_RE.split(text, maxsplit=1)[0].strip()
    paragraphs = [
        " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        for paragraph in re.split(r"\n\s*\n", text)
    ]
    for paragraph in paragraphs:
        if paragraph and not CODEX_FINDING_LINE_RE.match(paragraph):
            return paragraph
    return ""


def strip_finding_priority(finding: str) -> tuple[str, str]:
    match = re.match(r"^(\[P[0-3]\])\s+(.+)$", finding)
    if not match:
        return "", finding
    return match.group(1), match.group(2)
