from unittest.mock import MagicMock

import pytest

from llm.adapters.claude import ClaudeClient
from llm.client import LLMError


def _fake_response(tool_name: str, tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def test_claude_client_returns_tool_input_as_dict():
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response(
        "return_result", {"answer": 42}
    )
    client = ClaudeClient(sdk=sdk, model="claude-sonnet-4-6")

    result = client.chat_json(
        system="be helpful",
        user="what's the answer",
        json_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
    )

    assert result == {"answer": 42}
    call = sdk.messages.create.call_args
    assert call.kwargs["model"] == "claude-sonnet-4-6"
    assert call.kwargs["system"] == "be helpful"
    assert call.kwargs["tool_choice"] == {"type": "tool", "name": "return_result"}
    assert call.kwargs["tools"][0]["name"] == "return_result"


def test_claude_client_per_call_model_overrides_default():
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response(
        "return_result", {"answer": 1}
    )
    client = ClaudeClient(sdk=sdk, model="claude-sonnet-4-6")
    client.chat_json("s", "u", {"type": "object"}, model="claude-opus-4-7")
    assert sdk.messages.create.call_args.kwargs["model"] == "claude-opus-4-7"


def test_claude_client_streams_high_output_requests():
    sdk = MagicMock()
    stream = MagicMock()
    stream.get_final_message.return_value = _fake_response(
        "return_result", {"answer": 64}
    )
    sdk.messages.stream.return_value.__enter__.return_value = stream
    client = ClaudeClient(sdk=sdk, model="claude-haiku-4-5-20251001")

    result = client.chat_json(
        "s",
        "u",
        {"type": "object"},
        max_tokens=64000,
    )

    assert result == {"answer": 64}
    sdk.messages.create.assert_not_called()
    stream.until_done.assert_called_once()
    assert sdk.messages.stream.call_args.kwargs["max_tokens"] == 64000


def test_claude_client_falls_back_to_streaming_when_sdk_requires_it():
    sdk = MagicMock()
    sdk.messages.create.side_effect = ValueError("Streaming is required")
    stream = MagicMock()
    stream.get_final_message.return_value = _fake_response(
        "return_result", {"answer": 16}
    )
    sdk.messages.stream.return_value.__enter__.return_value = stream
    client = ClaudeClient(sdk=sdk, model="claude-opus-4-20250514")

    result = client.chat_json(
        "s",
        "u",
        {"type": "object"},
        max_tokens=16000,
    )

    assert result == {"answer": 16}
    sdk.messages.create.assert_called_once()
    stream.until_done.assert_called_once()
    assert sdk.messages.stream.call_args.kwargs["max_tokens"] == 16000


def test_claude_client_raises_when_no_tool_use_block():
    sdk = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    response = MagicMock()
    response.content = [text_block]
    sdk.messages.create.return_value = response
    client = ClaudeClient(sdk=sdk, model="claude-sonnet-4-6")

    with pytest.raises(LLMError, match="no tool_use block"):
        client.chat_json("s", "u", {"type": "object"})


def test_claude_client_web_search_adds_tool_and_uses_auto_choice():
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response("return_result", {"answer": 7})
    client = ClaudeClient(sdk=sdk, model="claude-sonnet-4-6")

    result = client.chat_json("s", "u", {"type": "object"}, enable_web_search=True)

    assert result == {"answer": 7}
    call_kwargs = sdk.messages.create.call_args.kwargs
    tool_types = [t.get("type") for t in call_kwargs["tools"]]
    assert "web_search_tool_20250305" in tool_types
    assert call_kwargs["tool_choice"] == {"type": "auto"}


def test_claude_client_web_search_false_keeps_forced_tool_choice():
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response("return_result", {"answer": 1})
    client = ClaudeClient(sdk=sdk, model="claude-sonnet-4-6")

    client.chat_json("s", "u", {"type": "object"}, enable_web_search=False)

    call_kwargs = sdk.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "return_result"}
    tool_types = [t.get("type") for t in call_kwargs["tools"]]
    assert "web_search_tool_20250305" not in tool_types


def test_claude_client_logs_token_usage(caplog):
    import logging
    sdk = MagicMock()
    response = _fake_response("return_result", {"r": 1})
    response.usage = MagicMock(input_tokens=120, output_tokens=55)
    sdk.messages.create.return_value = response
    client = ClaudeClient(sdk=sdk, model="claude-sonnet-4-6")

    with caplog.at_level(logging.DEBUG, logger="essay_writer.llm"):
        client.chat_json("s", "u", {"type": "object"})

    token_msgs = [r.message for r in caplog.records if "tokens" in r.message]
    assert token_msgs
    assert "120" in token_msgs[0]
    assert "55" in token_msgs[0]
