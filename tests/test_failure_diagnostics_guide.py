from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "60-runbooks" / "guide-001-failure-diagnostics-guide.md"


def test_failure_diagnostics_guide_documents_exit_codes():
    text = GUIDE.read_text(encoding="utf-8")
    for code in ("0", "1", "2", "3", "4", "5", "6"):
        assert f"| `{code}` |" in text
    for phrase in (
        "provider_quota_exhausted",
        "summary.phase_failures",
        "diagnostics.json",
        "revrem report <run-dir>",
        "Raw run-directory upload is opt-in",
    ):
        assert phrase in text
