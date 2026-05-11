from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.sources.schema import SourceChunk, SourceDocument
from essay_writer.sources.source_card_cache import SourceCardCache
from essay_writer.sources.summary import (
    SOURCE_CARD_SYSTEM_PROMPT,
    build_source_card,
    build_source_card_user_message,
    source_card_from_payload,
)
from tests.agent_tools._tmp import LocalAgentTempDir


def test_llm_source_card_uses_uploaded_excerpts_only_and_bounds_summary() -> None:
    source = SourceDocument(
        id="src1",
        original_path="source.pdf",
        file_name="source.pdf",
        source_type="pdf",
        page_count=3,
        char_count=5000,
        extraction_method="pypdf",
        text_quality="readable",
        full_text_available=False,
        indexed=True,
    )
    chunks = [
        SourceChunk(
            id="c1",
            source_id="src1",
            ordinal=1,
            page_start=1,
            page_end=1,
            text="This uploaded source analyzes urban heat, public health, and tree canopy policy.",
            char_count=78,
        )
    ]
    client = MockLLMClient(
        responses=[
            {
                "title": "Urban Heat and Public Health",
                "brief_summary": "x" * 500,
                "key_topics": ["urban heat", "public health"],
                "useful_for_topic_ideation": ["Supports topics about climate adaptation in cities."],
                "notable_sections": ["Page 1 introduces the policy problem."],
                "limitations": ["Only excerpts were provided."],
                "citation_metadata": {"file_name": "source.pdf"},
                "warnings": [],
            }
        ]
    )

    card = build_source_card(source, chunks, llm_client=client, summary_char_limit=220)
    user_payload = json.loads(client.calls[0]["user"])

    assert "Do not use web knowledge" in SOURCE_CARD_SYSTEM_PROMPT
    assert len(card.brief_summary) <= 220
    assert card.key_topics == ["urban heat", "public health"]
    assert user_payload["excerpts"][0]["text"].startswith("This uploaded source")


def test_public_source_card_user_message_emits_pipeline_json_shape() -> None:
    message = build_source_card_user_message(_source(), _chunks(), 300)
    payload = json.loads(message)

    assert payload == {
        "source": {
            "source_id": "src1",
            "file_name": "source.pdf",
            "source_type": "pdf",
            "page_count": 3,
            "extraction_method": "pypdf",
        },
        "summary_char_limit": 300,
        "excerpts": [
            {
                "chunk_id": "src1-c1",
                "pages": [1, 1],
                "text": "The same content appears across two ingestion runs. Lorem ipsum dolor sit amet.",
            }
        ],
    }


def test_source_card_from_payload_bounds_summary() -> None:
    card = source_card_from_payload(
        _source(),
        {**_payload(), "brief_summary": "x" * 500},
        summary_char_limit=220,
    )

    assert len(card.brief_summary) <= 220
    assert card.brief_summary.endswith("...")
    assert card.title == "Same Content"


def _source(source_id: str = "src1", file_name: str = "source.pdf") -> SourceDocument:
    return SourceDocument(
        id=source_id,
        original_path=file_name,
        file_name=file_name,
        source_type="pdf",
        page_count=3,
        char_count=5000,
        extraction_method="pypdf",
        text_quality="readable",
        full_text_available=False,
        indexed=True,
    )


def _chunks(source_id: str = "src1") -> list[SourceChunk]:
    return [
        SourceChunk(
            id=f"{source_id}-c1",
            source_id=source_id,
            ordinal=1,
            page_start=1,
            page_end=1,
            text="The same content appears across two ingestion runs. Lorem ipsum dolor sit amet.",
            char_count=80,
        )
    ]


def _payload(title: str = "Same Content") -> dict:
    return {
        "title": title,
        "brief_summary": "Summary.",
        "key_topics": ["topic"],
        "useful_for_topic_ideation": [],
        "notable_sections": [],
        "limitations": [],
        "citation_metadata": {},
        "warnings": [],
    }


def test_source_card_cache_skips_llm_call_on_identical_excerpts() -> None:
    """Second ingestion of identical content reads the cached LLM payload and
    skips the LLM call entirely — covers the cross-store/cross-job case."""
    with LocalAgentTempDir() as tmp:
        cache = SourceCardCache(tmp / "card_cache")
        client = MockLLMClient(responses=[_payload()])

        first = build_source_card(_source(), _chunks(), llm_client=client, cache=cache)
        second = build_source_card(_source(), _chunks(), llm_client=client, cache=cache)

    assert len(client.calls) == 1
    assert first.title == "Same Content"
    assert second.title == "Same Content"


def test_source_card_cache_hit_does_not_require_llm_client() -> None:
    """Once a card is cached, callers can hydrate without any LLM client —
    important for environments that lack an API key but already have cache."""
    with LocalAgentTempDir() as tmp:
        cache = SourceCardCache(tmp / "card_cache")
        seeded = MockLLMClient(responses=[_payload()])
        build_source_card(_source(), _chunks(), llm_client=seeded, cache=cache)

        card = build_source_card(_source(), _chunks(), llm_client=None, cache=cache)
    assert card.title == "Same Content"


def test_source_card_cache_key_ignores_source_id_and_file_name() -> None:
    """Cache key is content-driven so identical excerpts under a different
    source_id (e.g. UUID assigned by backend) still hit the cache."""
    with LocalAgentTempDir() as tmp:
        cache = SourceCardCache(tmp / "card_cache")
        client = MockLLMClient(responses=[_payload()])

        build_source_card(
            _source(source_id="src-aaa", file_name="paper.pdf"),
            _chunks(source_id="src-aaa"),
            llm_client=client,
            cache=cache,
        )
        build_source_card(
            _source(source_id="src-bbb", file_name="paper-renamed.pdf"),
            _chunks(source_id="src-bbb"),
            llm_client=client,
            cache=cache,
        )

    assert len(client.calls) == 1


def test_source_card_cache_distinguishes_different_excerpt_text() -> None:
    with LocalAgentTempDir() as tmp:
        cache = SourceCardCache(tmp / "card_cache")
        client = MockLLMClient(responses=[_payload("First"), _payload("Second")])

        build_source_card(_source(), _chunks(), llm_client=client, cache=cache)

        other_chunks = [
            SourceChunk(
                id="c1",
                source_id="src1",
                ordinal=1,
                page_start=1,
                page_end=1,
                text="Different excerpt content entirely. The cache must not collide.",
                char_count=64,
            )
        ]
        build_source_card(_source(), other_chunks, llm_client=client, cache=cache)

    assert len(client.calls) == 2


def test_source_card_cache_distinguishes_model() -> None:
    with LocalAgentTempDir() as tmp:
        cache = SourceCardCache(tmp / "card_cache")
        client = MockLLMClient(responses=[_payload(), _payload()])

        build_source_card(_source(), _chunks(), llm_client=client, cache=cache, model="claude-sonnet-4-6")
        build_source_card(_source(), _chunks(), llm_client=client, cache=cache, model="claude-opus-4-7")

    assert len(client.calls) == 2
