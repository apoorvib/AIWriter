from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.sources.schema import SourceCard, SourceIndexEntry, SourceIndexManifest
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.prompts import TOPIC_IDEATION_SYSTEM_PROMPT
from essay_writer.topic_ideation.service import TopicIdeationService


def test_topic_ideation_service_returns_structured_source_leads() -> None:
    task_spec = TaskSpecification(id="task1", version=1, raw_text="Write a policy essay.")
    card = SourceCard(
        source_id="src1",
        title="Urban Heat Report",
        source_type="pdf",
        page_count=20,
        extraction_method="pypdf",
        brief_summary="Discusses urban heat and housing risk.",
    )
    manifest = SourceIndexManifest(
        source_id="src1",
        index_path="internal.sqlite",
        total_chunks=1,
        total_chars=100,
        entries=[
            SourceIndexEntry(
                chunk_id="src1-chunk-0001",
                ordinal=1,
                page_start=1,
                page_end=1,
                char_count=100,
                heading="Urban Heat",
                preview="Heat risk affects renters.",
            )
        ],
    )
    client = MockLLMClient(
        responses=[
            {
                "blocking_questions": [],
                "warnings": [],
                "candidates": [
                    {
                        "title": "Urban heat as housing inequality",
                        "research_question": "How does urban heat expose housing inequality?",
                        "tentative_thesis_direction": "Cities should treat heat adaptation as housing policy.",
                        "rationale": "The source index points to housing and heat risk.",
                        "source_leads": [
                            {
                                "source_id": "src1",
                                "chunk_ids": ["src1-chunk-0001"],
                                "suggested_search_queries": ["urban heat renters housing"],
                            }
                        ],
                        "fit_score": 0.9,
                        "evidence_score": 0.8,
                        "originality_score": 0.7,
                        "risk_flags": [],
                        "missing_evidence": [],
                    }
                ],
            }
        ]
    )

    result = TopicIdeationService(client).generate(task_spec, source_cards=[card], index_manifests=[manifest])
    user_payload = client.calls[0]["user"]

    assert "source_id as the index handle" in TOPIC_IDEATION_SYSTEM_PROMPT
    assert "src1-chunk-0001" in user_payload
    assert "internal.sqlite" not in user_payload
    assert result.candidates[0].source_leads[0].chunk_ids == ["src1-chunk-0001"]
    assert result.candidates[0].source_leads[0].suggested_search_queries == ["urban heat renters housing"]
    assert json.loads(user_payload.split("\n\n", 1)[1])["source_index_manifests"][0]["index_handle"] == "src1"
