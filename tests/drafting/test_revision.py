from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.drafting.revision import DraftRevisionService
from essay_writer.drafting.schema import EssayDraft, SectionSourceMap
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.research.schema import EvidenceMap, ResearchNote
from essay_writer.sources.access_schema import SourceLocator, SourceTextPacket
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic
from essay_writer.validation.schema import (
    AssignmentFit,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    UnsupportedClaim,
    ValidationReport,
)


def test_revision_service_passes_source_packets_to_llm() -> None:
    client = MockLLMClient(
        responses=[
            {
                "content": "Revised draft.",
                "section_source_map": [
                    {
                        "section_id": "section_001",
                        "heading": "Body",
                        "note_ids": ["note_001"],
                        "source_ids": ["src1"],
                    }
                ],
                "bibliography_candidates": [],
                "known_weak_spots": [],
            }
        ]
    )
    service = DraftRevisionService(client)

    service.revise(
        EssayJob(id="job1", task_spec_id="task1", selected_topic_id="topic_001"),
        _task_spec(),
        _topic(),
        _evidence_map(),
        outline=_outline(),
        previous_draft=_previous_draft(),
        validation=_validation(),
        source_packets=[_source_packet()],
        version=2,
    )
    context = json.loads(client.calls[0]["user"].split("\n\n", 1)[1])

    assert context["source_packets"][0]["packet_id"] == "src1-pdf-pages-0002-0002"
    assert context["source_packets"][0]["source_id"] == "src1"
    assert context["source_packets"][0]["pdf_page_start"] == 2
    assert context["source_packets"][0]["text"] == "Source excerpt used for revision."


def _task_spec() -> TaskSpecification:
    return TaskSpecification(id="task1", version=1, raw_text="Write an essay.", citation_style="MLA")


def _topic() -> SelectedTopic:
    return SelectedTopic(
        job_id="job1",
        round_id="round1",
        topic_id="topic_001",
        title="Topic",
        research_question="Question?",
        tentative_thesis_direction="Thesis.",
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
                chunk_id="src1-packet",
                page_start=2,
                page_end=2,
                claim="Claim.",
                quote="Source excerpt used for revision.",
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


def _outline() -> ThesisOutline:
    return ThesisOutline(
        id="outline1",
        job_id="job1",
        selected_topic_id="topic_001",
        research_plan_id="plan1",
        evidence_map_id="evidence_map_v001",
        version=1,
        working_thesis="Thesis.",
        sections=[
            OutlineSection(
                id="section_001",
                heading="Body",
                purpose="support",
                key_points=["Claim."],
                note_ids=["note_001"],
            )
        ],
    )


def _previous_draft() -> EssayDraft:
    return EssayDraft(
        id="draft1",
        job_id="job1",
        version=1,
        selected_topic_id="topic_001",
        content="Old draft.",
        outline_id="outline1",
        section_source_map=[SectionSourceMap(section_id="section_001", heading="Body", note_ids=["note_001"])],
    )


def _validation() -> ValidationReport:
    return ValidationReport(
        draft_id="draft1",
        task_spec_id="task1",
        deterministic=DeterministicCheckResult(
            word_count=2,
            em_dash_count=0,
            tier1_vocab_hits=[],
            bad_conclusion_opener=False,
            consecutive_similar_sentence_runs=[],
            participial_phrase_count=0,
            participial_phrase_rate=0.0,
            contrastive_negation_count=0,
            signposting_hits=[],
        ),
        llm_judgment=LLMJudgmentResult(
            unsupported_claims=[UnsupportedClaim(claim="Unsupported.", paragraph=1)],
            citation_issues=[],
            rubric_scores=[],
            assignment_fit=AssignmentFit(passes=True, explanation="Fits."),
            length_check=LengthCheck(actual_words=2, target_words=None, passes=True),
            style_issues=[],
            revision_suggestions=["Ground the claim."],
            overall_quality=0.5,
        ),
    )


def _source_packet() -> SourceTextPacket:
    return SourceTextPacket(
        packet_id="src1-pdf-pages-0002-0002",
        source_id="src1",
        locator=SourceLocator(source_id="src1", locator_type="pdf_pages", pdf_page_start=2, pdf_page_end=2),
        text="Source excerpt used for revision.",
        pdf_page_start=2,
        pdf_page_end=2,
        extraction_method="pypdf",
        text_quality="readable",
    )
