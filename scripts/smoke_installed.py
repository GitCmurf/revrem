"""Exercise an installed wheel from a disposable repository, without model calls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def smoke(python: Path) -> None:
    python = python.absolute()
    with tempfile.TemporaryDirectory(prefix="revrem-package-smoke-") as directory:
        root = Path(directory)
        repo = root / "repo"
        repo.mkdir()
        fixtures = root / "fixtures"
        for scenario, response in (
            ("clear", "No actionable findings.\nREVIEW_STATUS: clear\n"),
            ("findings", "[P1] Fix the arithmetic in calculator.py:1\nREVIEW_STATUS: findings\n"),
        ):
            path = fixtures / scenario
            path.mkdir(parents=True)
            (path / "review.txt").write_text(response)
            (path / "remediation.txt").write_text("No edit in deterministic smoke.\n")
        env = {**os.environ, "REVREM_ALLOW_FAKE_HARNESS": "1",
               "REVREM_FAKE_HARNESS_FIXTURE_DIR": str(fixtures),
               "XDG_DATA_HOME": str(root / "data")}

        def run(args: list[str], expected: int = 0) -> str:
            result = subprocess.run(args, cwd=repo, env=env, capture_output=True,
                                    text=True, timeout=60, check=False)
            if result.returncode != expected:
                raise RuntimeError(f"{args}: expected {expected}, got {result.returncode}\n"
                                   f"{result.stdout}\n{result.stderr}")
            return result.stdout

        run(["git", "init", "-b", "main"])
        (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
        run(["git", "add", "calculator.py"])
        run(["git", "-c", "user.name=Package Smoke", "-c", "user.email=smoke@example.invalid",
             "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
             "commit", "-m", "test: package smoke fixture"])
        cli = [str(python), "-I", "-m", "code_review_loop"]
        rows = json.loads(run([*cli, "models", "list", "--format", "json"]))
        assert {"gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"} <= {row["id"] for row in rows}
        run([*cli, "doctor", "--base", "main", "--codex-bin", "git", "--format", "json",
             "--artifact-dir", str(root / "doctor")])
        for scenario, code in (("clear", 0), ("findings", 2)):
            artifacts = root / scenario
            run([*cli, "--base", "main", "--review-harness", "fake", "--review-model", scenario,
                 "--remediation-harness", "fake", "--remediation-model", scenario,
                 "--no-triage", "--no-routing", "--no-commit-after-remediation",
                 "--max-iterations", "1", "--max-wall-seconds", "30",
                 "--no-run-history", "--no-tty", "--artifact-dir", str(artifacts),
                 "--check", "git diff --check"], expected=code)
            summary = json.loads((artifacts / "summary.json").read_text())
            assert summary["final_status"] == scenario
            assert (artifacts / "events.jsonl").is_file()
            run([*cli, "report", str(artifacts), "--output", str(root / f"{scenario}.html")])
            assert "<html" in (root / f"{scenario}.html").read_text().lower()
        run([*cli, "--profile", "security", "--base", "main", "--dry-run", "--no-run-history",
             "--artifact-dir", str(root / "expert")])
    print("Installed-package acceptance passed: models, doctor, clear/findings loops, reports, expert profile.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/smoke_installed.py /absolute/venv/bin/python")
    smoke(Path(sys.argv[1]))
