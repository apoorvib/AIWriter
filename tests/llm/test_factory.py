import pytest

from llm.adapters.claude import ClaudeClient
from llm.adapters.gemini import GeminiClient
from llm.adapters.openai_ import OpenAIClient
from llm.factory import make_client


def test_factory_selects_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = make_client("claude")
    assert isinstance(client, ClaudeClient)


def test_factory_selects_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = make_client("openai")
    assert isinstance(client, OpenAIClient)


def test_factory_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    client = make_client("gemini")
    assert isinstance(client, GeminiClient)


def test_factory_reads_env_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = make_client()
    assert isinstance(client, OpenAIClient)


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unknown provider"):
        make_client("bard")


def test_factory_errors_when_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(KeyError, match="ANTHROPIC_API_KEY"):
        make_client("claude")


def test_factory_error_message_names_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(KeyError, match="openai"):
        make_client("openai")
