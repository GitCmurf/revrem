# Expected Findings

This file is the stable ledger for seeded issues in the reference fixture repo.
It is intentionally specific enough for future profile tests to map findings
back to files without requiring exact model wording.

| ID | Class | File | Line | Severity | Expected signal |
|---|---|---:|---:|---|---|
| RF-001 | security | `src/reference_app/auth.py` | 9 | critical | SQL query uses string interpolation with untrusted `username`. |
| RF-002 | maintainability | `src/reference_app/auth.py` | 5 | low | Unused import remains in production module. |
| RF-003 | reliability | `src/reference_app/auth.py` | 15 | medium | Broad `except Exception` hides database errors. |
| RF-004 | maintainability | `src/reference_app/billing.py` | 5 | medium | Email normalization helper duplicated. |
| RF-005 | reliability | `src/reference_app/billing.py` | 22 | medium | Broad `except Exception` hides payment failures. |
| RF-006 | performance | `src/reference_app/reporting.py` | 5 | medium | Nested loop creates avoidable O(n*m) report generation. |
| RF-007 | docs | `src/reference_app/docs.py` | 4 | low | Public function lacks docstring and type annotations. |

When this fixture changes, update this ledger and
`tests/test_fixtures.py::test_reference_repo_expected_findings_are_present`
in the same PR.
