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
    client = ClaudeClient(sdk=sdk, model="claude-opus-4-7")

    result = client.chat_json(
        system="be helpful",
        user="what's the answer",
        json_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
    )

    assert result == {"answer": 42}
    call = sdk.messages.create.call_args
    assert call.kwargs["model"] == "claude-opus-4-7"
    assert call.kwargs["system"] == "be helpful"
    assert call.kwargs["tool_choice"] == {"type": "tool", "name": "return_result"}
    assert call.kwargs["tools"][0]["name"] == "return_result"


def test_claude_client_raises_when_no_tool_use_block():
    sdk = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    response = MagicMock()
    response.content = [text_block]
    sdk.messages.create.return_value = response
    client = ClaudeClient(sdk=sdk, model="claude-opus-4-7")

    with pytest.raises(LLMError, match="no tool_use block"):
        client.chat_json("s", "u", {"type": "object"})
