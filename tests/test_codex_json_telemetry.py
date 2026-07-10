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
