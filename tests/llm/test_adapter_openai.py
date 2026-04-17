import json
from unittest.mock import MagicMock

import pytest

from llm.adapters.openai_ import OpenAIClient
from llm.client import LLMError


def _fake_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def test_openai_client_parses_json_content():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response(json.dumps({"n": 7}))
    client = OpenAIClient(sdk=sdk, model="gpt-4o-2024-11-20")

    result = client.chat_json(
        system="sys",
        user="usr",
        json_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
    )

    assert result == {"n": 7}
    kwargs = sdk.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-2024-11-20"
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["name"] == "result"
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["messages"][1] == {"role": "user", "content": "usr"}


def test_openai_client_raises_on_invalid_json():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response("not json")
    client = OpenAIClient(sdk=sdk, model="gpt-4o-2024-11-20")

    with pytest.raises(LLMError, match="invalid JSON"):
        client.chat_json("s", "u", {"type": "object"})
