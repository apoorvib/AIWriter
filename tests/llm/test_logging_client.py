from __future__ import annotations

import logging

import pytest

from llm.logging_client import LoggingLLMClient
from llm.mock import MockLLMClient


def test_logging_client_passes_call_through_to_inner():
    inner = MockLLMClient(responses=[{"key": "value"}])
    client = LoggingLLMClient(inner, stage="drafting")

    result = client.chat_json("sys", "usr", {"type": "object"}, max_tokens=500, model="m1")

    assert result == {"key": "value"}
    assert inner.calls[0]["system"] == "sys"
    assert inner.calls[0]["user"] == "usr"
    assert inner.calls[0]["model"] == "m1"


def test_logging_client_logs_start_and_done(caplog):
    inner = MockLLMClient(responses=[{"x": 1}])
    client = LoggingLLMClient(inner, stage="validation")

    with caplog.at_level(logging.INFO, logger="essay_writer.llm"):
        client.chat_json("sys", "usr", {})

    messages = [r.message for r in caplog.records]
    assert any("llm.call.start" in m and "validation" in m for m in messages)
    assert any("llm.call.done" in m and "validation" in m for m in messages)


def test_logging_client_logs_error_on_failure(caplog):
    class BrokenClient:
        def chat_json(self, *a, **kw):
            raise RuntimeError("boom")

    client = LoggingLLMClient(BrokenClient(), stage="research")

    with caplog.at_level(logging.ERROR, logger="essay_writer.llm"):
        with pytest.raises(RuntimeError, match="boom"):
            client.chat_json("s", "u", {})

    assert any("llm.call.error" in r.message and "research" in r.message for r in caplog.records)


def test_logging_client_includes_char_counts_in_start_log(caplog):
    inner = MockLLMClient(responses=[{}])
    client = LoggingLLMClient(inner, stage="topic_ideation")

    with caplog.at_level(logging.INFO, logger="essay_writer.llm"):
        client.chat_json("x" * 100, "y" * 2000, {})

    start_msgs = [r.message for r in caplog.records if "llm.call.start" in r.message]
    assert start_msgs
    assert "sys_chars=100" in start_msgs[0]
    assert "user_chars=2000" in start_msgs[0]


def test_logging_client_passes_enable_web_search_to_inner():
    inner = MockLLMClient(responses=[{}])
    client = LoggingLLMClient(inner, stage="research")

    client.chat_json("s", "u", {}, enable_web_search=True)

    assert inner.calls[0]["enable_web_search"] is True


def test_logging_client_default_stage_label(caplog):
    inner = MockLLMClient(responses=[{}])
    client = LoggingLLMClient(inner)

    with caplog.at_level(logging.INFO, logger="essay_writer.llm"):
        client.chat_json("s", "u", {})

    assert any("unknown" in r.message for r in caplog.records)
