import pytest
from code_review_loop import harnesses

def test_claude_adapter_command():
    adapter = harnesses.ClaudeHarnessAdapter()
    req = harnesses.PhaseCommandRequest(harness="claude", role="triage", executable="claude", model="m1")
    cmd = adapter.command(req)
    assert cmd == ["claude", "--print", "--model", "m1"]

def test_gemini_adapter_command():
    adapter = harnesses.GeminiHarnessAdapter()
    req = harnesses.PhaseCommandRequest(harness="gemini", role="remediation", executable="gemini")
    cmd = adapter.command(req)
    assert cmd == ["gemini", "--prompt"]

def test_opencode_adapter_command():
    adapter = harnesses.OpenCodeHarnessAdapter()
    req = harnesses.PhaseCommandRequest(harness="opencode", role="remediation", executable="oc", model="m2")
    cmd = adapter.command(req)
    assert cmd == ["oc", "run", "--model", "m2"]

def test_kilo_adapter_command():
    adapter = harnesses.KiloHarnessAdapter()
    req = harnesses.PhaseCommandRequest(harness="kilo", role="triage", executable="kilo")
    cmd = adapter.command(req)
    assert cmd == ["kilo", "run"]
