from __future__ import annotations

from code_review_loop import fingerprints


def test_finding_fingerprint_matches_golden_vector():
    finding = fingerprints.FindingFingerprintInput(
        rule_id="B608",
        path="src/reference_app/auth.py",
        message="Possible SQL injection vector through string-based query construction.",
        severity="high",
    )

    assert fingerprints.finding_fingerprint(finding) == "f1:c6ace015ccd20120"


def test_finding_fingerprint_normalizes_message_whitespace_and_case():
    compact = fingerprints.FindingFingerprintInput(
        rule_id="B608",
        path="src/reference_app/auth.py",
        message="Possible SQL injection vector through string-based query construction.",
        severity="high",
    )
    noisy = fingerprints.FindingFingerprintInput(
        rule_id="B608",
        path="src/reference_app/auth.py",
        message="  Possible SQL injection VECTOR\nthrough string-based\tquery construction.  ",
        severity="HIGH",
    )

    assert fingerprints.finding_fingerprint(noisy) == fingerprints.finding_fingerprint(compact)


def test_finding_fingerprint_preserves_path_case_and_severity_bucket():
    base = fingerprints.FindingFingerprintInput(
        rule_id="B608",
        path="src/reference_app/auth.py",
        message="Possible SQL injection vector through string-based query construction.",
        severity="high",
    )
    renamed_case = fingerprints.FindingFingerprintInput(
        rule_id="B608",
        path="src/reference_app/Auth.py",
        message="Possible SQL injection vector through string-based query construction.",
        severity="high",
    )
    lower_severity = fingerprints.FindingFingerprintInput(
        rule_id="B608",
        path="src/reference_app/auth.py",
        message="Possible SQL injection vector through string-based query construction.",
        severity="medium",
    )

    assert fingerprints.finding_fingerprint(renamed_case) != fingerprints.finding_fingerprint(base)
    assert fingerprints.finding_fingerprint(lower_severity) != fingerprints.finding_fingerprint(base)


def test_finding_fingerprint_normalizes_paths_without_filesystem_case_rules():
    finding = fingerprints.FindingFingerprintInput(
        rule_id=None,
        path=r".\src\reference_app\auth.py",
        message="Undocumented public function.",
        severity="unknown",
    )

    assert fingerprints.normalize_rule_id(finding.rule_id) == "<none>"
    assert fingerprints.normalize_path(finding.path) == "src/reference_app/auth.py"
    assert fingerprints.normalize_severity(finding.severity) == "info"
