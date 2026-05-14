from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_REPO = ROOT / "tests" / "fixtures" / "reference-repo"


def test_reference_repo_present():
    assert (REFERENCE_REPO / "pyproject.toml").is_file()
    assert (REFERENCE_REPO / "README.md").is_file()
    assert (REFERENCE_REPO / "EXPECTED_FINDINGS.md").is_file()
    assert (REFERENCE_REPO / "src" / "reference_app" / "auth.py").is_file()
    assert (REFERENCE_REPO / "src" / "reference_app" / "billing.py").is_file()
    assert (REFERENCE_REPO / "src" / "reference_app" / "reporting.py").is_file()
    assert (REFERENCE_REPO / "src" / "reference_app" / "docs.py").is_file()


def test_reference_repo_expected_findings_are_present():
    expected = (REFERENCE_REPO / "EXPECTED_FINDINGS.md").read_text(encoding="utf-8")

    for finding_id in ("RF-001", "RF-002", "RF-003", "RF-004", "RF-005", "RF-006", "RF-007"):
        assert finding_id in expected

    assert "SQL query uses string interpolation" in expected
    assert "Unused import" in expected
    assert "Broad `except Exception`" in expected
    assert "Email normalization helper duplicated" in expected
    assert "O(n*m)" in expected
    assert "lacks docstring and type annotations" in expected
