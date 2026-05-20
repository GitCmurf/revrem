from __future__ import annotations

from code_review_loop import triage


def test_triage_safety_scan_path_traversal_prevention(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("password = '123'", encoding="utf-8")

    payload = {
        "confirmed_findings": [{"affected_paths": ["../secret.txt"]}],
        "classification": {},
    }

    # Should NOT find 'password' because of traversal block
    context = triage.extract_routing_context(payload, repo)
    assert "sensitive-domain:secrets" not in context.safety_signals


def test_triage_safety_scan_oversized_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    large = repo / "large.txt"
    with open(large, "wb") as f:
        f.write(b"A" * triage.MAX_SAFETY_SCAN_BYTES)
        f.write(b"password")  # Beyond cap

    payload = {
        "confirmed_findings": [{"affected_paths": ["large.txt"]}],
        "classification": {},
    }

    # Should NOT find 'password' because it reads only up to cap
    context = triage.extract_routing_context(payload, repo)
    assert "sensitive-domain:secrets" not in context.safety_signals

def test_triage_safety_scan_unreadable_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    unreadable = repo / "unreadable.txt"
    unreadable.touch()
    unreadable.chmod(0) # Make unreadable

    payload = {
        "confirmed_findings": [{"affected_paths": ["unreadable.txt"]}],
        "classification": {},
    }

    # Should not crash
    context = triage.extract_routing_context(payload, repo)
    assert context is not None

def test_triage_safety_scan_symlink_escape(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("password = '123'", encoding="utf-8")

    # Symlink pointing outside repo
    sym = repo / "sym.txt"
    sym.symlink_to(secret)

    payload = {
        "confirmed_findings": [{"affected_paths": ["sym.txt"]}],
        "classification": {},
    }

    context = triage.extract_routing_context(payload, repo)
    # is_relative_to(cwd_resolved) should block it because full_path.resolve() evaluates the symlink
    assert "sensitive-domain:secrets" not in context.safety_signals
