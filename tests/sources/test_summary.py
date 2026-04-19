from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.sources.schema import SourceChunk, SourceDocument
from essay_writer.sources.summary import SOURCE_CARD_SYSTEM_PROMPT, build_source_card


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
