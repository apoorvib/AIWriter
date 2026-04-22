from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.drafting.schema import EssayDraft, SectionSourceMap
from essay_writer.drafting.style_revision import FinalStyleRevisionService
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.research.schema import EvidenceMap, ResearchNote
from essay_writer.sources.access_schema import SourceLocator, SourceTextPacket
from essay_writer.task_spec.schema import TaskSpecification


def test_style_revision_preserves_metadata_and_passes_source_packets() -> None:
    client = MockLLMClient(
        responses=[
            {
                "content": "Styled draft with the same supported claim.",
                "style_changes": ["Removed generic phrasing."],
                "preservation_notes": ["No citations changed."],
                "known_risks": ["Paragraph 2 may still be too even."],
            }
        ]
    )
    service = FinalStyleRevisionService(client)

    styled = service.revise_style(
        job=EssayJob(id="job1", task_spec_id="task1", selected_topic_id="topic_001"),
        task_spec=TaskSpecification(id="task1", version=1, raw_text="Write an essay."),
        draft=_draft(),
        outline=_outline(),
        evidence_map=_evidence_map(),
        source_packets=[_source_packet()],
        version=2,
    )
    context = json.loads(client.calls[0]["user"])

    assert styled.id != "draft1"
    assert styled.version == 2
    assert styled.content == "Styled draft with the same supported claim."
    assert styled.section_source_map[0].note_ids == ["note_001"]
    assert styled.bibliography_candidates == ["Source citation."]
    assert "Paragraph 2 may still be too even." in styled.known_weak_spots
    assert context["source_packets"][0]["packet_id"] == "src1-pdf-pages-0002-0002"
    assert context["source_packets"][0]["text"] == "Source excerpt."
    assert "deterministic_style_issues" in context


def _draft() -> EssayDraft:
    return EssayDraft(
        id="draft1",
        job_id="job1",
        version=1,
        selected_topic_id="topic_001",
        content="Old draft.",
        outline_id="outline1",
        section_source_map=[
            SectionSourceMap(section_id="section_001", heading="Body", note_ids=["note_001"], source_ids=["src1"])
        ],
        bibliography_candidates=["Source citation."],
    )


def _outline() -> ThesisOutline:
    return ThesisOutline(
        id="outline1",
        job_id="job1",
        selected_topic_id="topic_001",
        research_plan_id="plan1",
        evidence_map_id="evidence_map_v001",
        version=1,
        working_thesis="Thesis.",
        sections=[OutlineSection(id="section_001", heading="Body", purpose="support", key_points=["Claim."])],
    )


def _evidence_map() -> EvidenceMap:
    return EvidenceMap(
        id="evidence_map_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        research_question="Question?",
        thesis_direction="Thesis.",
        notes=[
            ResearchNote(
                id="note_001",
                source_id="src1",
                chunk_id="packet1",
                page_start=2,
                page_end=2,
                claim="Claim.",
                quote="Source excerpt.",
                paraphrase="Paraphrase.",
                relevance="Relevant.",
                supports_topic=True,
                evidence_type="support",
                confidence=0.9,
            )
        ],
        evidence_groups=[],
        gaps=[],
        conflicts=[],
    )


def _source_packet() -> SourceTextPacket:
    return SourceTextPacket(
        packet_id="src1-pdf-pages-0002-0002",
        source_id="src1",
        locator=SourceLocator(source_id="src1", locator_type="pdf_pages", pdf_page_start=2, pdf_page_end=2),
        text="Source excerpt.",
        pdf_page_start=2,
        pdf_page_end=2,
        extraction_method="pypdf",
        text_quality="readable",
    )
