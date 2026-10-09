"""Acceptance failures must still fail when Python removes assertions."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", ["models", "status", "events", "report", None])
def test_optimized_acceptance_rejects_invalid_installed_output(tmp_path, monkeypatch, failure):
    script = Path(__file__).resolve().parents[1] / "scripts/smoke_installed.py"
    module = types.ModuleType("optimized_smoke")
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec", optimize=2), module.__dict__)

    def run(args, **kwargs):
        stdout, code = "", 0
        if "models" in args:
            models = [] if failure == "models" else ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"]
            stdout = json.dumps([{"id": model} for model in models])
        elif "--review-model" in args:
            scenario = args[args.index("--review-model") + 1]
            code = 0 if scenario == "clear" else 2
            artifacts = Path(args[args.index("--artifact-dir") + 1])
            artifacts.mkdir()
            status = "unknown" if failure == "status" else scenario
            (artifacts / "summary.json").write_text(json.dumps({"final_status": status}), encoding="utf-8")
            if failure != "events":
                (artifacts / "events.jsonl").write_text("{}\n", encoding="utf-8")
        elif "report" in args:
            content = "broken report" if failure == "report" else "<html></html>"
            Path(args[-1]).write_text(content, encoding="utf-8")
        return subprocess.CompletedProcess(args, code, stdout, "")

    monkeypatch.setattr(module.subprocess, "run", run)
    if failure is None:
        module.smoke(Path(sys.executable))
    else:
        with pytest.raises(RuntimeError):
            module.smoke(Path(sys.executable))
