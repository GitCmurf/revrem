from code_review_loop.adapters.subprocess_runner import _normalize_codex_json


def test_codex_json_normalizes_final_message_and_token_usage():
    raw = (
        '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}\n'
    )

    stdout, tokens, provider_events = _normalize_codex_json(
        ["codex", "exec", "--json", "-"], raw
    )

    assert stdout == "done\n"
    assert tokens == 15
    assert provider_events == raw


def test_codex_json_uses_error_event_text_when_final_assistant_message_is_absent():
    raw = (
        '{"type":"item.completed","item":{"type":"error","message":"authentication required"}}\n'
    )

    stdout, tokens, provider_events = _normalize_codex_json(
        ["codex", "exec", "--json", "-"], raw
    )

    assert stdout == "authentication required\n"
    assert tokens is None
    assert provider_events == raw


def test_codex_json_falls_back_to_raw_json_when_no_final_or_error_text_exists():
    raw = '{"type":"item.completed","item":{"type":"tool_result","data":{"ok":true}}}\n'

    stdout, tokens, provider_events = _normalize_codex_json(
        ["codex", "exec", "--json", "-"], raw
    )

    assert stdout == raw
    assert tokens is None
    assert provider_events == raw


def test_codex_json_extracts_typed_content_blocks():
    raw = (
        '{"type":"item.completed","item":{"type":"agent_message",'
        '"content":[{"type":"output_text","text":"first"},'
        '{"type":"output_text","text":"second"}]}}\n'
    )

    stdout, tokens, provider_events = _normalize_codex_json(
        ["codex", "exec", "--json", "-"], raw
    )

    assert stdout == "first\nsecond\n"
    assert tokens is None
    assert provider_events == raw
