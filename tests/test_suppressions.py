from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from code_review_loop import suppressions
from code_review_loop._compat_jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def test_suppression_add_list_remove_and_audit_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("REVREM_SUPPRESSION_ACTOR", "tester")
    path = tmp_path / ".revrem" / "suppressions.toml"
    audit = tmp_path / ".revrem" / "suppressions.audit.jsonl"
    entry = suppressions.make_entry(
        fingerprint="f1:abc123",
        summary="Known false positive",
        rationale="The reviewed path is generated and checked elsewhere.",
        severity="medium",
        scope="repo",
        expires_at=None,
        critical_override=False,
    )

    suppressions.add_entry(path, entry, audit_path=audit)

    assert suppressions.load_entries(path) == [entry]
    assert tomllib.loads(path.read_text(encoding="utf-8"))["suppressions"][0]["fingerprint"] == "f1:abc123"
    audit_records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert audit_records[0]["action"] == "add"
    assert audit_records[0]["actor"] == "tester"

    assert suppressions.remove_entry(path, "f1:abc123", audit_path=audit) is True
    assert suppressions.load_entries(path) == []
    assert tomllib.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": "1.0",
        "suppressions": [],
    }


def test_critical_suppression_requires_override_and_short_expiry():
    with pytest.raises(ValueError, match="critical_override"):
        suppressions.make_entry(
            fingerprint="f1:critical",
            summary="Critical issue",
            rationale="Temporarily accepted.",
            severity="critical",
            scope="repo",
            expires_at="2026-06-01T00:00:00Z",
            critical_override=False,
            created_at="2026-05-12T00:00:00Z",
        )

    with pytest.raises(ValueError, match="within 30 days"):
        suppressions.make_entry(
            fingerprint="f1:critical",
            summary="Critical issue",
            rationale="Temporarily accepted.",
            severity="critical",
            scope="repo",
            expires_at="2026-07-01T00:00:00Z",
            critical_override=True,
            created_at="2026-05-12T00:00:00Z",
        )


def test_load_entries_rejects_non_boolean_critical_override(tmp_path):
    path = tmp_path / ".revrem" / "suppressions.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        """
schema_version = "1.0"

[[suppressions]]
fingerprint = "f1:critical"
summary = "Critical issue"
rationale = "Temporarily accepted."
created_at = "2026-05-12T00:00:00Z"
created_by = "tester"
scope = "repo"
severity_at_suppression = "critical"
critical_override = "false"
expires_at = "2026-05-13T00:00:00Z"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="critical_override must be a boolean"):
        suppressions.load_entries(path)


def test_effective_suppressions_ignore_expired_and_repo_overrides_user(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    (cwd / ".git").mkdir(parents=True)
    now = datetime(2026, 5, 12, tzinfo=UTC)
    user_entry = suppressions.make_entry(
        fingerprint="f1:same",
        summary="User suppression",
        rationale="User-specific rationale.",
        severity="low",
        scope="user",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-01T00:00:00Z",
    )
    repo_entry = suppressions.make_entry(
        fingerprint="f1:same",
        summary="Repo suppression",
        rationale="Team-shared rationale.",
        severity="low",
        scope="repo",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-01T00:00:00Z",
    )
    expired_entry = suppressions.make_entry(
        fingerprint="f1:expired",
        summary="Expired suppression",
        rationale="No longer valid.",
        severity="low",
        scope="repo",
        expires_at="2026-05-01T00:00:00Z",
        critical_override=False,
        created_at="2026-04-01T00:00:00Z",
    )
    suppressions.write_entries(suppressions.user_suppressions_path(home), [user_entry])
    suppressions.write_entries(suppressions.repo_suppressions_path(cwd), [repo_entry, expired_entry])

    effective = suppressions.load_effective_suppressions(cwd, home=home, now=now)

    assert effective["f1:same"].entry.summary == "Repo suppression"
    assert "f1:expired" not in effective


def test_apply_to_triage_payload_moves_suppressed_confirmed_findings(tmp_path):
    entry = suppressions.make_entry(
        fingerprint="f1:abc123",
        summary="Accepted risk",
        rationale="Tracked elsewhere.",
        severity="high",
        scope="repo",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-12T00:00:00Z",
    )
    payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:abc123",
                "summary": "Fix SQL injection",
                "severity": "high",
                "affected_paths": ["src/auth.py"],
                "rationale": "Raw SQL uses user input.",
            }
        ],
        "implementation_order": ["f1:abc123"],
    }

    updated, suppressed = suppressions.apply_to_triage_payload(
        payload,
        {"f1:abc123": suppressions.SuppressionMatch(entry, tmp_path / ".revrem/suppressions.toml")},
    )

    assert updated["confirmed_findings"] == []
    assert updated["implementation_order"] == []
    assert suppressed[0]["suppressed"] is True
    assert suppressed[0]["suppression"]["rationale"] == "Tracked elsewhere."


def test_apply_to_triage_payload_keeps_critical_findings_when_suppression_is_noncritical(tmp_path):
    entry = suppressions.make_entry(
        fingerprint="f1:abc123",
        summary="Accepted risk",
        rationale="Tracked elsewhere.",
        severity="medium",
        scope="repo",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-12T00:00:00Z",
    )
    payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:abc123",
                "summary": "Fix SQL injection",
                "severity": "critical",
                "affected_paths": ["src/auth.py"],
                "rationale": "Raw SQL uses user input.",
            }
        ],
        "implementation_order": ["f1:abc123"],
    }

    updated, suppressed = suppressions.apply_to_triage_payload(
        payload,
        {"f1:abc123": suppressions.SuppressionMatch(entry, tmp_path / ".revrem/suppressions.toml")},
    )

    assert updated["confirmed_findings"] == payload["confirmed_findings"]
    assert updated["implementation_order"] == payload["implementation_order"]
    assert updated["suppressed_findings"] == []
    assert suppressed == []


def test_rendered_suppression_file_validates_against_schema(tmp_path):
    entry = suppressions.make_entry(
        fingerprint="f1:abc123",
        summary="Accepted risk",
        rationale="Tracked elsewhere.",
        severity="medium",
        scope="repo",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-12T00:00:00Z",
    )
    path = tmp_path / ".revrem" / "suppressions.toml"
    suppressions.write_entries(path, [entry])

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "docs/52-api/schemas/suppressions-v1.schema.json").read_text(encoding="utf-8")
    )

    validate(payload, schema)


def test_audit_summary_omits_rationale_and_actor_values(tmp_path):
    path = tmp_path / ".revrem" / "suppressions.audit.jsonl"
    suppressions.append_audit(
        path,
        "add",
        [],
        [
            {
                "fingerprint": "f1:abc123",
                "rationale": "Sensitive rationale from colin@example.com",
            }
        ],
    )

    summary = suppressions.audit_summary(path)

    assert summary == {"schema_version": "1.0", "total_records": 1, "actions": {"add": 1}}
