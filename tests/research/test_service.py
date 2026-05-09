from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.jobs.schema import EssayJob
from essay_writer.research.prompts import FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT
from essay_writer.research.service import FinalTopicResearchService
from essay_writer.task_spec.schema import ChecklistItem, TaskSpecification
from essay_writer.topic_ideation.schema import (
    RetrievedTopicEvidence,
    SelectedTopic,
    TopicEvidenceChunk,
)


def test_final_topic_research_extracts_grounded_notes_and_groups() -> None:
    client = MockLLMClient(
        responses=[
            {
                "notes": [
                    {
                        "source_id": "src1",
                        "chunk_id": "chunk1",
                        "page_start": 2,
                        "page_end": 3,
                        "claim": "Urban heat affects renters in older housing.",
                        "quote": "Urban heat affects renters in older housing.",
                        "paraphrase": "The source links heat risk to rental housing conditions.",
                        "relevance": "Supports the selected topic's housing-inequality angle.",
                        "supports_topic": True,
                        "evidence_type": "argument",
                        "tags": ["urban heat", "housing"],
                        "confidence": 0.9,
                    }
                ],
                "evidence_groups": [
                    {
                        "label": "Housing inequality",
                        "purpose": "thesis_support",
                        "note_ids": ["note_001"],
                        "synthesis": "Heat risk can be framed as a housing inequality issue.",
                    }
                ],
                "gaps": ["Need a source on policy outcomes."],
                "conflicts": [],
                "warnings": [],
            }
        ]
    )

    result = FinalTopicResearchService(client).extract(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        retrieved_evidence=[_retrieved_evidence()],
    )
    blocks = client.calls[0]["user_blocks"]
    static_payload = json.loads(blocks[0].text)

    assert blocks[0].cacheable is True
    assert blocks[1].cacheable is False
    assert "Use only the supplied" in FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT
    assert static_payload["selected_topic"]["topic_id"] == "topic_001"
    assert static_payload["retrieved_chunks"][0]["chunk_id"] == "chunk1"
    assert result.evidence_map.notes[0].source_id == "src1"
    assert result.evidence_map.notes[0].chunk_id == "chunk1"
    assert result.evidence_map.notes[0].quote == "Urban heat affects renters in older housing."
    assert result.evidence_map.evidence_groups[0].note_ids == ["note_001"]
    assert result.report.note_count == 1
    assert result.report.gaps == ["Need a source on policy outcomes."]


def test_final_topic_research_drops_invalid_chunk_and_bad_quote_references() -> None:
    client = MockLLMClient(
        responses=[
            {
                "notes": [
                    {
                        "source_id": "src1",
                        "chunk_id": "missing",
                        "page_start": 1,
                        "page_end": 1,
                        "claim": "Bad chunk.",
                        "quote": None,
                        "paraphrase": "Bad chunk.",
                        "relevance": "None.",
                        "supports_topic": True,
                        "evidence_type": "argument",
                        "tags": [],
                        "confidence": 0.5,
                    },
                    {
                        "source_id": "src1",
                        "chunk_id": "chunk1",
                        "page_start": 99,
                        "page_end": 100,
                        "claim": "Heat affects renters.",
                        "quote": "This quote is not in the chunk.",
                        "paraphrase": "Heat risk affects renters.",
                        "relevance": "Relevant to housing inequality.",
                        "supports_topic": True,
                        "evidence_type": "not-real",
                        "tags": ["heat"],
                        "confidence": 2.0,
                    },
                ],
                "evidence_groups": [
                    {
                        "label": "Bad group references",
                        "purpose": "unknown",
                        "note_ids": ["note_001", "missing_note"],
                        "synthesis": "Only valid notes should remain.",
                    }
                ],
                "gaps": [],
                "conflicts": [],
                "warnings": [],
            }
        ]
    )

    result = FinalTopicResearchService(client).extract(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        retrieved_evidence=[_retrieved_evidence()],
    )

    assert len(result.evidence_map.notes) == 1
    note = result.evidence_map.notes[0]
    assert note.id == "note_001"
    assert note.chunk_id == "chunk1"
    assert note.quote is None
    assert note.page_start == 2
    assert note.page_end == 3
    assert note.evidence_type == "other"
    assert note.confidence == 1.0
    assert result.evidence_map.evidence_groups[0].purpose == "other"
    assert result.evidence_map.evidence_groups[0].note_ids == ["note_001"]
    assert any("unknown chunk_id" in warning for warning in result.report.warnings)
    assert any("not found in chunk" in warning for warning in result.report.warnings)
    assert any("Corrected page range" in warning for warning in result.report.warnings)


def test_research_dedupes_overlapping_packet_and_retrieved_chunks() -> None:
    """P9: a packet derived from explicit page locator and a retrieved FTS
    chunk can carry the SAME text under different chunk_ids. Sending both
    wastes ~25k+ tokens when retrievals overlap heavily."""
    from essay_writer.sources.access_schema import SourceLocator, SourceTextPacket

    client = MockLLMClient(
        responses=[
            {"notes": [], "evidence_groups": [], "gaps": [], "conflicts": [], "warnings": []}
        ]
    )

    duplicate_text = "Urban heat affects renters in older housing. Cooling centers are unevenly distributed."

    packet = SourceTextPacket(
        packet_id="src1-pdf-pages-0002-0003",
        source_id="src1",
        locator=SourceLocator(source_id="src1", locator_type="pdf_pages", pdf_page_start=2, pdf_page_end=3),
        text=duplicate_text,
        pdf_page_start=2,
        pdf_page_end=3,
        extraction_method="pypdf",
        text_quality="readable",
    )
    retrieved = RetrievedTopicEvidence(
        topic_id="topic_001",
        chunks=[
            TopicEvidenceChunk(
                source_id="src1",
                chunk_id="src1-chunk-0042",
                page_start=2,
                page_end=3,
                text=duplicate_text,
                score=0.1,
            )
        ],
    )

    FinalTopicResearchService(client).extract(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        retrieved_evidence=[retrieved],
        source_packets=[packet],
    )
    static_payload = json.loads(client.calls[0]["user_blocks"][0].text)

    assert len(static_payload["retrieved_chunks"]) == 1


def test_research_static_block_is_byte_stable_for_cache_reuse() -> None:
    """P9: the same retrieval should produce a byte-identical cacheable
    prefix on re-runs so the prompt cache hits."""
    client = MockLLMClient(
        responses=[
            {"notes": [], "evidence_groups": [], "gaps": [], "conflicts": [], "warnings": []},
            {"notes": [], "evidence_groups": [], "gaps": [], "conflicts": [], "warnings": []},
        ]
    )
    service = FinalTopicResearchService(client)

    service.extract(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        retrieved_evidence=[_retrieved_evidence()],
    )
    service.extract(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        retrieved_evidence=[_retrieved_evidence()],
    )

    first_static = client.calls[0]["user_blocks"][0].text
    second_static = client.calls[1]["user_blocks"][0].text
    assert first_static == second_static


def test_final_topic_research_returns_gap_without_evidence_or_llm_call() -> None:
    client = MockLLMClient(responses=[])

    result = FinalTopicResearchService(client).extract(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        retrieved_evidence=[],
    )

    assert client.calls == []
    assert result.evidence_map.notes == []
    assert result.evidence_map.gaps == ["No retrieved source evidence was available for this topic."]
    assert result.report.warnings == ["No retrieved source chunks were available for final topic research."]


def _job() -> EssayJob:
    return EssayJob(
        id="job1",
        status="research_planning_ready",
        current_stage="research_planning",
        task_spec_id="task1",
        source_ids=["src1"],
        selected_topic_id="topic_001",
    )


def _task_spec() -> TaskSpecification:
    return TaskSpecification(
        id="task1",
        version=1,
        raw_text="Write a policy essay using sources.",
        citation_style="MLA",
        extracted_checklist=[
            ChecklistItem(
                id="req_001",
                text="Use sources.",
                category="source",
                required=True,
                source_span="Use sources.",
                confidence=0.9,
            )
        ],
    )


def _selected_topic() -> SelectedTopic:
    return SelectedTopic(
        job_id="job1",
        round_id="round1",
        topic_id="topic_001",
        title="Urban heat and housing inequality",
        research_question="How does urban heat affect housing inequality?",
        tentative_thesis_direction="Urban heat policy should be treated as housing policy.",
    )


def _retrieved_evidence() -> RetrievedTopicEvidence:
    return RetrievedTopicEvidence(
        topic_id="topic_001",
        chunks=[
            TopicEvidenceChunk(
                source_id="src1",
                chunk_id="chunk1",
                page_start=2,
                page_end=3,
                text="Urban heat affects renters in older housing. Cooling centers are unevenly distributed.",
                score=0.1,
            )
        ],
    )
