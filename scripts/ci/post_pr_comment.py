#!/usr/bin/env python3
"""Post an idempotent RevRem PR comment from a report index (PLAN-005 T4).

Reads the already-redacted revrem-report.json produced by
revrem report --format json and posts (or updates) a single PR comment
marked with a stable marker comment. The body builder is pure and unit-tested
in isolation from the GitHub HTTP layer.

Environment (all required for posting):
  GITHUB_TOKEN         - a pull-requests: write token
  GITHUB_REPOSITORY    - owner/repo (set by the Actions runner)
  GITHUB_PR_NUMBER     - PR issue number (the action passes this explicitly)
  GITHUB_RUN_URL       - optional, a link to the workflow run (fallback link)
  REVREM_ARTIFACT_URL  - optional, deep-link to the uploaded report artifact;
                         preferred over GITHUB_RUN_URL in the comment footer
  REVREM_REPORT_JSON   - path to the redacted report index (default
                         revrem-report.json in the cwd)

Fork-PR model: the action gates this script. It never prints secrets - the
input is already redacted by revrem report.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MARKER = "<!-- revrem-report -->"
_API_BASE = "https://api.github.com"


def _md_cell(value: Any) -> str:
    """Make a value safe to drop into a Markdown table cell.

    Neutralises the column delimiter (`|`) and collapses line breaks so a
    model-derived string (e.g. a finding title) cannot add columns, split the
    row, or escape into block formatting. Backticks are replaced with a single
    quote so a stray backtick cannot open an unterminated code span.
    """
    text = "" if value is None else str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "'")
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def build_comment_body(
    report_index: dict[str, Any], *, report_url: str = "", run_url: str = ""
) -> str:
    """Build the markdown PR comment body from a report index.

    Pure: no I/O, no network. The input is the already-redacted index from
    revrem report --format json; this function never re-redacts and never
    embeds raw model output or stderr. The body is bounded: at most the top 5
    findings (already capped by the index) and a fixed set of summary rows.
    """
    final_status = str(report_index.get("final_status", "unknown"))
    stopped_reason = report_index.get("stopped_reason") or ""
    counts = report_index.get("finding_counts") or {}
    suppression = report_index.get("suppression_count", 0)
    cost = report_index.get("cost_usd")
    top = report_index.get("top_findings") or []
    failure = report_index.get("failure_summary")

    status_emoji = {
        "clear": "white_check_mark",
        "findings": "x",
        "unknown": "grey_question",
        "error": "rotating_light",
    }.get(final_status, "grey_question")

    lines: list[str] = [MARKER, ""]
    lines.append(f"## :{status_emoji}: RevRem review - `{final_status}`")
    lines.append("")

    total_findings = sum(counts.get(s, 0) for s in ("critical", "high", "medium", "low"))
    sev_row = " | ".join(
        f"{s}: {counts.get(s, 0)}" for s in ("critical", "high", "medium", "low")
    )
    cost_str = f"${cost:.2f}" if isinstance(cost, (int, float)) else "n/a"
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| **Findings** | {_md_cell(f'{total_findings} ({sev_row})')} |")
    if suppression:
        lines.append(f"| **Suppressed** | {suppression} |")
    lines.append(f"| **Cost** | {cost_str} |")
    if stopped_reason:
        lines.append(f"| **Stop reason** | `{_md_cell(stopped_reason)}` |")
    if isinstance(failure, dict):
        message = failure.get("message") or failure.get("detail") or failure.get("reason")
        if message:
            lines.append(f"| **Failure** | {_md_cell(message)} |")
    lines.append("")

    if top:
        lines.append("### Top findings")
        lines.append("")
        lines.append("| Severity | File | Finding |")
        lines.append("|---|---|---|")
        for finding in top:
            severity = _md_cell(finding.get("severity", "?"))
            file_path = finding.get("file") or "-"
            line = finding.get("line")
            loc = _md_cell(f"{file_path}:{line}" if line else file_path)
            title = _md_cell(finding.get("title") or "(no detail)")
            lines.append(f"| {severity} | `{loc}` | {title} |")
        lines.append("")

    provenance = "See the uploaded revrem-report.html artifact for the full report."
    # Deep-link the report artifact when we captured its URL; otherwise fall back
    # to the workflow run. Label each link for what it actually points at — a
    # "[Run]" link that resolves to the artifact (or vice versa) is misleading.
    if report_url:
        provenance += f" [Report]({report_url})."
    elif run_url:
        provenance += f" [Run]({run_url})."
    lines.append(f"<sub>{provenance}</sub>")

    return "\n".join(lines)


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "revrem-pr-comment",
    }


def _find_existing_comment(
    token: str, repo: str, pr_number: str, api_base: str
) -> str | None:
    """Return the comment id of the existing RevRem comment, or None.

    Follows the ``Link: <url>; rel="next"`` header across pages so a long-lived
    PR with more than 100 comments still finds the marked comment (the marker is
    the idempotency key — missing it would create a duplicate on every run).
    """
    url: str | None = (
        f"{api_base}/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    )
    while url is not None:
        req = urllib.request.Request(url, headers=_auth_headers(token))
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - trusted GitHub API
            comments = json.loads(resp.read().decode("utf-8"))
            link = resp.headers.get("Link")
        for comment in comments:
            body = comment.get("body", "") or ""
            if MARKER in body:
                return str(comment.get("id"))
        url = _next_link(link) if link else None
    return None


def _next_link(link_header: str) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub ``Link`` header, or None."""
    for part in link_header.split(","):
        segment = part.strip()
        if 'rel="next"' not in segment:
            continue
        start = segment.find("<")
        end = segment.find(">", start + 1)
        if start != -1 and end != -1:
            return segment[start + 1 : end]
    return None


def post_or_update_comment(
    body: str,
    *,
    token: str,
    repo: str,
    pr_number: str,
) -> str:
    """Create a new comment or update the existing marked one. Returns the action taken.

    Reads ``_API_BASE`` as a module global at call time so tests can point it
    at a local stub via monkeypatch.
    """
    api_base = _API_BASE
    existing = _find_existing_comment(token, repo, pr_number, api_base)
    if existing:
        url = f"{api_base}/repos/{repo}/issues/comments/{existing}"
        method = "PATCH"
        action = "updated"
    else:
        url = f"{api_base}/repos/{repo}/issues/{pr_number}/comments"
        method = "POST"
        action = "created"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers=_auth_headers(token),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - trusted GitHub API
        resp.read()
    return action


def main(argv: list[str]) -> int:
    report_path = os.environ.get("REVREM_REPORT_JSON", "revrem-report.json")
    try:
        with open(report_path, encoding="utf-8") as fh:
            report_index = json.load(fh)
    except (OSError, ValueError) as exc:
        print(
            f"ERROR: cannot read redacted report {report_path}: {exc}",
            file=sys.stderr,
        )
        report_index = {"final_status": "unknown", "stopped_reason": "report-unavailable"}

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number = os.environ.get("GITHUB_PR_NUMBER", "")
    report_url = os.environ.get("REVREM_ARTIFACT_URL", "")
    run_url = os.environ.get("GITHUB_RUN_URL", "")

    if not (token and repo and pr_number):
        print(
            "ERROR: GITHUB_TOKEN, GITHUB_REPOSITORY, and GITHUB_PR_NUMBER are required.",
            file=sys.stderr,
        )
        return 1

    body = build_comment_body(report_index, report_url=report_url, run_url=run_url)
    try:
        action = post_or_update_comment(
            body, token=token, repo=repo, pr_number=pr_number
        )
    except (urllib.error.URLError, ValueError) as exc:
        print(f"ERROR: GitHub API request failed: {exc}", file=sys.stderr)
        return 1
    print(f"revrem comment {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
