#!/usr/bin/env python3
"""Verify priority-severity normalization for a captured triage artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main(argv: list[str] | None = None) -> int:
    from code_review_loop import triage

    parser = argparse.ArgumentParser(
        description="Parse a captured triage artifact and report normalized severities."
    )
    parser.add_argument("artifact", type=Path, help="Path to triage-N.txt or triage-N.json")
    parser.add_argument("--contract", choices=("v1", "v2"), default="v2")
    args = parser.parse_args(argv)

    raw = args.artifact.read_text(encoding="utf-8")
    json_part = raw.split("\n\n[stderr]", 1)[0].strip()
    payload = triage.parse_triage_payload(
        json_part,
        run_id="verify-triage-priority-artifact",
        source_review_artifact=args.artifact.name,
        contract=args.contract,
    )
    severities = [
        str(finding["severity"])
        for collection in ("confirmed_findings", "rejected_findings", "needs_more_info")
        for finding in payload.get(collection, [])
    ]
    print(f"severity={','.join(severities) if severities else 'none'}")
    for warning in payload.get("parsing_warnings", []):
        if "Normalized" in str(warning):
            print(f"normalized={warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
