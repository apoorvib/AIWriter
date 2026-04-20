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
                        "parent_topic_id": None,
                        "novelty_note": "Initial source-grounded topic.",
                        "source_leads": [
                            {
                                "source_id": "src1",
                                "chunk_ids": ["src1-chunk-0001"],
                                "suggested_source_search_queries": ["urban heat renters housing"],
                            }
                        ],
                        "source_requests": [
                            {
                                "source_id": "src1",
                                "locator_type": "pdf_pages",
                                "pdf_page_start": 2,
                                "pdf_page_end": 4,
                                "printed_page_label": None,
                                "section_id": None,
                                "query": None,
                                "chunk_id": None,
                                "reason": "Relevant report section.",
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
    assert result.candidates[0].source_leads[0].suggested_source_search_queries == ["urban heat renters housing"]
    assert result.candidates[0].source_requests[0].pdf_page_start == 2
    assert result.candidates[0].source_requests[0].pdf_page_end == 4
    assert result.candidates[0].parent_topic_id is None
    assert result.candidates[0].novelty_note == "Initial source-grounded topic."
    assert json.loads(user_payload.split("\n\n", 1)[1])["source_index_manifests"][0]["index_handle"] == "src1"
    assert "external web" in user_payload


def test_topic_ideation_service_includes_user_instruction_and_previous_candidates() -> None:
    task_spec = TaskSpecification(id="task1", version=1, raw_text="Write a policy essay.")
    card = SourceCard(
        source_id="src1",
        title="Urban Heat Report",
        source_type="pdf",
        page_count=20,
        extraction_method="pypdf",
        brief_summary="Discusses urban heat and housing risk.",
    )
    previous = [
        _candidate(
            title="Urban heat as housing inequality",
            research_question="How does urban heat expose housing inequality?",
        )
    ]
    client = MockLLMClient(
        responses=[
            {
                "blocking_questions": [],
                "warnings": [],
                "candidates": [
                    {
                        "title": "Cooling centers and unequal access",
                        "research_question": "Who benefits from cooling-center policy?",
                        "tentative_thesis_direction": "Cooling-center policy can reproduce unequal access.",
                        "rationale": "This refines the earlier heat topic toward public-service access.",
                        "parent_topic_id": "topic_old",
                        "novelty_note": "Narrows the prior topic toward cooling access.",
                        "source_leads": [],
                        "source_requests": [],
                        "fit_score": 0.8,
                        "evidence_score": 0.7,
                        "originality_score": 0.8,
                        "risk_flags": [],
                        "missing_evidence": [],
                    }
                ],
            }
        ]
    )

    from essay_writer.topic_ideation.schema import RejectedTopic

    result = TopicIdeationService(client).generate(
        task_spec,
        source_cards=[card],
        previous_candidates=previous,
        rejected_topics=[
            RejectedTopic(
                job_id="job1",
                round_id="round1",
                topic_id="topic_rejected",
                title="Generic heat topic",
                reason="Too broad.",
            )
        ],
        user_instruction="Give me more choices, but make them narrower and less obvious.",
    )
    context = json.loads(client.calls[0]["user"].split("\n\n", 1)[1])

    assert context["user_instruction"] == "Give me more choices, but make them narrower and less obvious."
    assert context["previous_candidates"][0]["id"] == "topic_old"
    assert context["previous_candidates"][0]["title"] == "Urban heat as housing inequality"
    assert context["rejected_topics"][0]["title"] == "Generic heat topic"
    assert context["rejected_topics"][0]["reason"] == "Too broad."
    assert "rejected_topics" in client.calls[0]["user"]
    assert result.candidates[0].parent_topic_id == "topic_old"
    assert result.candidates[0].novelty_note == "Narrows the prior topic toward cooling access."


def _candidate(*, title: str, research_question: str):
    from essay_writer.topic_ideation.schema import CandidateTopic, TopicSourceLead

    return CandidateTopic(
        id="topic_old",
        title=title,
        research_question=research_question,
        tentative_thesis_direction="Prior thesis direction.",
        rationale="Prior rationale.",
        source_leads=[
            TopicSourceLead(
                source_id="src1",
                chunk_ids=["src1-chunk-0001"],
            )
        ],
        fit_score=0.8,
        evidence_score=0.7,
        originality_score=0.6,
    )
