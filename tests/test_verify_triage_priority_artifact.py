from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_triage_priority_artifact.py"


def test_verify_triage_priority_artifact_reports_normalized_priority(tmp_path: Path) -> None:
    artifact = tmp_path / "triage-1.txt"
    payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:p2",
                "summary": "Strict route falls back",
                "severity": "P2",
                "affected_paths": ["src/code_review_loop/policy.py"],
                "rationale": "Review priority should normalize before schema validation.",
            }
        ],
        "rejected_findings": [],
        "needs_more_info": [],
        "implementation_order": ["f1:p2"],
        "verification_commands": ["pytest"],
        "parsing_warnings": [],
        "classification": {
            "domain_tags": ["routing"],
            "risk_level": "medium",
            "refactor_depth": "localised",
            "affected_modules": ["code_review_loop"],
            "estimated_blast_radius": {"finding_count": 1, "module_count": 1},
            "safety_signals": [],
            "failed_check_signals": [],
        },
        "prompt_requirements": {
            "required_fragments": [],
            "definition_of_done": ["P2 normalizes to medium."],
            "triage_prompt_draft": "Fix the routing issue.",
        },
    }
    artifact.write_text(json.dumps(payload) + "\n\n[stderr]\nignored\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(artifact)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "severity=medium" in result.stdout
    assert "normalized=Normalized confirmed_findings severity 'P2' to 'medium'." in result.stdout


def test_verify_triage_priority_artifact_fails_for_invalid_payload(tmp_path: Path) -> None:
    artifact = tmp_path / "triage-1.txt"
    artifact.write_text('{"confirmed_findings": []}\n', encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(artifact)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
