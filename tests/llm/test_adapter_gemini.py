import json
from unittest.mock import MagicMock

import pytest

from llm.adapters.gemini import GeminiClient
from llm.client import LLMError


def _fake_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    return response


def test_gemini_client_parses_json_text():
    model = MagicMock()
    model.generate_content.return_value = _fake_response(json.dumps({"v": "ok"}))
    client = GeminiClient(model_obj=model, model_name="gemini-2.5-pro")

    result = client.chat_json(
        system="sys",
        user="usr",
        json_schema={"type": "object", "properties": {"v": {"type": "string"}}},
    )

    assert result == {"v": "ok"}
    call = model.generate_content.call_args
    combined = call.args[0][0]
    assert "sys" in combined
    assert "usr" in combined
    cfg = call.kwargs["generation_config"]
    assert cfg["response_mime_type"] == "application/json"
    assert cfg["response_schema"] == {
        "type": "object",
        "properties": {"v": {"type": "string"}},
    }


def test_gemini_client_raises_on_invalid_json():
    model = MagicMock()
    model.generate_content.return_value = _fake_response("oops")
    client = GeminiClient(model_obj=model, model_name="gemini-2.5-pro")

    with pytest.raises(LLMError, match="invalid JSON"):
        client.chat_json("s", "u", {"type": "object"})
