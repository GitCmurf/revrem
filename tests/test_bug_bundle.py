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
        "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890\n",  # pragma: allowlist secret
        encoding="utf-8",
    )
    (run_dir / "diagnostics-1.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "iteration": 1,
                "detail": "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",  # pragma: allowlist secret
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "review-1-status.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "classification": "unknown",
                "reason": "needs manual review",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "profile.toml").write_text(
        'codex_bin = "codex"\n# token-like local value should be scrubbed\napi_key = "ghp_abcdefghijklmnopqrstuvwxyzABCDE1234567890"\n',  # pragma: allowlist secret
        encoding="utf-8",
    )
    (run_dir / "doctor.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "ok",
                "local_path": str(Path.home() / "private"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "review-1.txt").write_text(
        "Raw transcript with ghp_abcdefghijklmnopqrstuvwxyzABCDE1234567890\n",  # pragma: allowlist secret
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
        "diagnostics-1.json",
        "doctor.json",
        "nested/events.jsonl",
        "profile.toml",
        "review-1-status.json",
        "summary.json",
    ]
    bundle_bytes = b"\n".join(members.values())
    assert b"secret-token" not in bundle_bytes
    assert b"sk-proj-" not in bundle_bytes
    assert b"ghp_" not in bundle_bytes
    assert b"/home/cmf/private" not in bundle_bytes
    manifest = json.loads(members["bug-bundle.json"])
    validate(manifest, json.loads((ROOT / "docs/52-api/schemas/bug-bundle-v1.schema.json").read_text()))
    assert "diagnostics-1.json" in manifest["files"]
    assert "review-1-status.json" in manifest["files"]
    assert manifest["include_raw_transcripts"] is False
    assert manifest["redacted"] is True
    assert manifest["redaction_counts"]["authorization-header"] == 1
    assert manifest["redaction_counts"]["openai-key"] == 2


def test_create_bug_bundle_uses_safe_default_output_path_for_untrusted_run_id(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps({"schema_version": "1.0", "run_id": "foo/../../evil"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "check-1.txt").write_text("check output\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = bug_bundle.create_bug_bundle(bug_bundle.BundleOptions(run_dir=run_dir))

    assert result.output_path == tmp_path / "revrem-bug-evil.tar.gz"
    assert result.output_path.parent == tmp_path
    assert result.output_path.is_file()


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
    assert "review-1-status.json" in members
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


def test_create_bug_bundle_skips_symlinked_artifacts(tmp_path):
    run_dir = _make_run_dir(tmp_path)
    outside_secret = tmp_path / "outside-secret.txt"
    outside_secret.write_text("TOP SECRET\n", encoding="utf-8")
    (run_dir / "check-output.txt").symlink_to(outside_secret)
    (run_dir / "summary.json").unlink()
    (run_dir / "summary.json").symlink_to(outside_secret)

    result = bug_bundle.create_bug_bundle(
        bug_bundle.BundleOptions(run_dir=run_dir, output_path=tmp_path / "bundle.tar.gz")
    )

    members = _bundle_members(result.output_path)
    assert "check-output.txt" not in members
    assert "summary.json" not in members
    assert result.manifest["run_id"] == "run"


def test_create_bug_bundle_includes_redacted_suppression_audit_summary(tmp_path):
    repo_root = tmp_path / "repo"
    run_dir = repo_root / ".revrem" / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"schema_version": "1.0", "run_id": "run-123"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "check-1.txt").write_text("check output\n", encoding="utf-8")
    (run_dir / "nested").mkdir()
    (run_dir / "nested" / "events.jsonl").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
    audit_path = repo_root / ".revrem" / "suppressions.audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "action": "add",
                "actor": "colin@example.com",
                "after": [{"rationale": "Sensitive local path /home/cmf/project"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = bug_bundle.create_bug_bundle(
        bug_bundle.BundleOptions(run_dir=run_dir, output_path=tmp_path / "bundle.tar.gz")
    )

    members = _bundle_members(result.output_path)
    assert "suppressions/suppressions.audit.summary.json" in members
    assert b"colin@example.com" not in members["suppressions/suppressions.audit.summary.json"]
    assert b"/home/cmf" not in members["suppressions/suppressions.audit.summary.json"]
    manifest = json.loads(members["bug-bundle.json"])
    assert manifest["suppression_audit_summaries"] == [
        "suppressions/suppressions.audit.summary.json"
    ]
    assert ".revrem/suppressions.audit.jsonl" not in members
