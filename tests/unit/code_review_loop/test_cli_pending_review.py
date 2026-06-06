import importlib
import sys
from unittest.mock import MagicMock

# Force import the module, not the aliased function in __init__.py
cli_main = importlib.import_module("code_review_loop.cli.main")

def test_apply_pending_review_choice_auto_no_prompt(monkeypatch):
    config = MagicMock()
    config.initial_review_file = None
    args = MagicMock()
    args.pending_review = "auto"
    
    # Simulate an incompatible candidate
    monkeypatch.setattr(cli_main, "_pending_review_candidate", lambda c: None)
    monkeypatch.setattr(cli_main, "_pending_review_candidate_ignoring_git", lambda c: MagicMock())
    
    # Ensure sys.stdin.isatty and sys.stdout.isatty return True (interactive)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    
    prompt_mock = MagicMock()
    monkeypatch.setattr(cli_main, "_prompt_for_pending_review", prompt_mock)
    
    result = cli_main._apply_pending_review_choice(config, args)
    
    # It should not prompt, and should return the unmodified config
    prompt_mock.assert_not_called()
    assert result is config

def test_apply_pending_review_choice_prompt(monkeypatch):
    config = MagicMock()
    config.initial_review_file = None
    args = MagicMock()
    args.pending_review = "prompt"
    
    # Simulate an incompatible candidate
    monkeypatch.setattr(cli_main, "_pending_review_candidate", lambda c: None)
    incompatible_candidate = MagicMock()
    monkeypatch.setattr(cli_main, "_pending_review_candidate_ignoring_git", lambda c: incompatible_candidate)
    
    # Ensure sys.stdin.isatty and sys.stdout.isatty return True (interactive)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    
    prompt_mock = MagicMock()
    prompt_mock.return_value = "modified_config"
    monkeypatch.setattr(cli_main, "_prompt_for_pending_review", prompt_mock)
    
    result = cli_main._apply_pending_review_choice(config, args)
    
    # It should prompt
    prompt_mock.assert_called_once_with(config, incompatible_candidate, compatible=False)
    assert result == "modified_config"
