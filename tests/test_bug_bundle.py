from __future__ import annotations

import json
import tarfile
from pathlib import Path

from code_review_loop import bug_bundle
from code_review_loop._compat_jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def _make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps({"schema_version": "1.0", "run_id": "run-123"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "check-1.txt").write_text(
        "Authorization: Bearer secret-token\n"
        "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890\n",
        encoding="utf-8",
    )
    (run_dir / "review-1.txt").write_text(
        "Raw transcript with ghp_abcdefghijklmnopqrstuvwxyzABCDE1234567890\n",
        encoding="utf-8",
    )
    (run_dir / "nested").mkdir()
    (run_dir / "nested" / "events.jsonl").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
    return run_dir


def _bundle_members(path: Path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as tar:
        members = {}
        for member in tar.getmembers():
            if member.isfile():
                extracted = tar.extractfile(member)
                assert extracted is not None
                members[member.name] = extracted.read()
        return members


def test_create_bug_bundle_redacts_default_contents_and_excludes_raw_transcripts(tmp_path):
    run_dir = _make_run_dir(tmp_path)

    result = bug_bundle.create_bug_bundle(
        bug_bundle.BundleOptions(run_dir=run_dir, output_path=tmp_path / "bundle.tar.gz")
    )

    members = _bundle_members(result.output_path)
    assert sorted(members) == [
        "bug-bundle.json",
        "check-1.txt",
        "nested/events.jsonl",
        "summary.json",
    ]
    bundle_bytes = b"\n".join(members.values())
    assert b"secret-token" not in bundle_bytes
    assert b"sk-proj-" not in bundle_bytes
    assert b"ghp_" not in bundle_bytes
    manifest = json.loads(members["bug-bundle.json"])
    validate(manifest, json.loads((ROOT / "docs/52-api/schemas/bug-bundle-v1.schema.json").read_text()))
    assert manifest["include_raw_transcripts"] is False
    assert manifest["redacted"] is True
    assert manifest["redaction_counts"]["authorization-header"] == 1
    assert manifest["redaction_counts"]["openai-key"] == 1


def test_create_bug_bundle_can_include_raw_transcripts_still_redacted(tmp_path):
    run_dir = _make_run_dir(tmp_path)

    result = bug_bundle.create_bug_bundle(
        bug_bundle.BundleOptions(
            run_dir=run_dir,
            output_path=tmp_path / "bundle.tar.gz",
            include_raw_transcripts=True,
        )
    )

    members = _bundle_members(result.output_path)
    assert "review-1.txt" in members
    assert b"ghp_" not in members["review-1.txt"]
    manifest = json.loads(members["bug-bundle.json"])
    assert manifest["include_raw_transcripts"] is True


def test_create_bug_bundle_is_deterministic(tmp_path):
    run_dir = _make_run_dir(tmp_path)
    first = bug_bundle.create_bug_bundle(
        bug_bundle.BundleOptions(run_dir=run_dir, output_path=tmp_path / "first.tar.gz")
    )
    second = bug_bundle.create_bug_bundle(
        bug_bundle.BundleOptions(run_dir=run_dir, output_path=tmp_path / "second.tar.gz")
    )

    assert first.output_path.read_bytes() == second.output_path.read_bytes()
