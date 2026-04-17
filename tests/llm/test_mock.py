import pytest

from llm.client import LLMClient
from llm.mock import MockLLMClient


def test_mock_returns_queued_response():
    client = MockLLMClient(responses=[{"foo": 1}, {"foo": 2}])
    assert client.chat_json("s", "u", {}) == {"foo": 1}
    assert client.chat_json("s", "u", {}) == {"foo": 2}


def test_mock_records_calls():
    client = MockLLMClient(responses=[{"x": 1}])
    client.chat_json("sys-text", "user-text", {"type": "object"}, max_tokens=100)
    assert len(client.calls) == 1
    assert client.calls[0]["system"] == "sys-text"
    assert client.calls[0]["user"] == "user-text"
    assert client.calls[0]["max_tokens"] == 100


def test_mock_raises_when_exhausted():
    client = MockLLMClient(responses=[{"x": 1}])
    client.chat_json("s", "u", {})
    with pytest.raises(RuntimeError, match="ran out of responses"):
        client.chat_json("s", "u", {})


def test_mock_conforms_to_protocol():
    assert isinstance(MockLLMClient(responses=[]), LLMClient)
