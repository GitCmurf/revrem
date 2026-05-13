from __future__ import annotations

from pathlib import Path

from code_review_loop import redaction

ROOT = Path(__file__).resolve().parents[1]


def test_redact_text_removes_poisoned_fixture_tokens():
    original = (ROOT / "tests" / "fixtures" / "redaction" / "poisoned" / "sample.txt").read_text(
        encoding="utf-8"
    )

    result = redaction.redact_text(
        original,
        home="/home/example-user",
        user="example-user",
    )

    assert "secret-token" not in result.text
    assert "sk-proj-" not in result.text
    assert "ghp_" not in result.text
    assert "AKIAABCDEFGHIJKLMNOP" not in result.text
    assert "sk-ant-" not in result.text
    assert "0123456789abcdef0123456789abcdef" not in result.text
    assert "abcdef0123456789abcdef0123456789" not in result.text
    assert "/home/example-user" not in result.text
    assert "actor=example-user" not in result.text
    assert "BEGIN PRIVATE KEY" not in result.text
    assert redaction.redaction_summary(result) == {
        "anthropic-key": 1,
        "authorization-header": 1,
        "aws-access-key": 1,
        "env-assignment": 1,
        "generic-token": 1,
        "github-token": 1,
        "home-path": 1,
        "openai-key": 1,
        "private-key": 1,
        "user": 1,
    }


def test_redact_text_is_idempotent():
    original = (ROOT / "tests" / "fixtures" / "redaction" / "poisoned" / "sample.txt").read_text(
        encoding="utf-8"
    )

    once = redaction.redact_text(original, home="/home/example-user", user="example-user")
    twice = redaction.redact_text(once.text, home="/home/example-user", user="example-user")

    assert twice.text == once.text
    assert redaction.redaction_summary(twice) == {}


def test_redact_text_leaves_clean_fixture_unchanged():
    original = (ROOT / "tests" / "fixtures" / "redaction" / "clean" / "sample.txt").read_text(
        encoding="utf-8"
    )

    result = redaction.redact_text(original, home="/home/example-user", user="example-user")

    assert result.text == original
    assert result.findings == ()


def test_redact_text_uses_optional_detect_secrets_when_available(monkeypatch):
    class FakeSecret:
        secret_value = "scanner-only-secret"

    class FakeScanModule:
        @staticmethod
        def scan_line(line):
            if "scanner-only-secret" in line:
                return iter([FakeSecret()])
            return iter(())

    def fake_import_module(name):
        assert name == "detect_secrets.core.scan"
        return FakeScanModule

    monkeypatch.setattr(redaction, "import_module", fake_import_module)

    result = redaction.redact_text("token=scanner-only-secret\n")

    assert "scanner-only-secret" not in result.text
    assert "[REDACTED:detect-secrets]" in result.text
    assert redaction.redaction_summary(result)["detect-secrets"] == 1
