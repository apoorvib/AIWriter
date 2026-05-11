from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.service import ThesisOutlineService
from essay_writer.research.schema import EvidenceGroup, EvidenceMap, ResearchNote
from essay_writer.research_planning.schema import ResearchPlan
from essay_writer.sources.access_schema import SourceLocator, SourceTextPacket
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic


def test_thesis_outline_uses_research_plan_evidence_groups_and_word_targets() -> None:
    outline = ThesisOutlineService(
        MockLLMClient(
            responses=[
                {
                    "working_thesis": "Heat policy should be housing policy.",
                    "sections": [
                        {
                            "heading": "Introduction",
                            "purpose": "introduce topic and thesis",
                            "key_points": ["How does heat affect renters?", "Heat policy should be housing policy"],
                            "note_ids": [],
                            "target_words": 140,
                        },
                        {
                            "heading": "Housing risk",
                            "purpose": "thesis_support",
                            "key_points": ["Heat risk supports a housing-policy argument."],
                            "note_ids": ["note_001"],
                            "target_words": 220,
                        },
                        {
                            "heading": "Conclusion",
                            "purpose": "synthesize argument",
                            "key_points": ["Return to the thesis and source-grounded stakes."],
                            "note_ids": [],
                            "target_words": 100,
                        },
                    ],
                }
            ]
        )
    ).create_outline(
        job=EssayJob(id="job1", task_spec_id="task1", selected_topic_id="topic_001"),
        task_spec=TaskSpecification(
            id="task1",
            version=1,
            raw_text="Write 1000 words.",
            target_length=1000,
            length_unit="words",
        ),
        selected_topic=_selected_topic(),
        research_plan=_plan(),
        evidence_map=_evidence_map(),
    )

    assert outline.id == "thesis_outline_v001"
    assert outline.research_plan_id == "research_plan_v001"
    assert outline.evidence_map_id == "evidence_map_v001"
    assert outline.working_thesis == "Heat policy should be housing policy."
    assert outline.sections[0].heading == "Introduction"
    assert outline.sections[0].target_words == 140
    assert outline.sections[1].heading == "Housing risk"
    assert outline.sections[1].note_ids == ["note_001"]
    assert outline.sections[-1].heading == "Conclusion"


def test_outline_prompt_is_style_aware_and_receives_full_source_packet_metadata() -> None:
    client = MockLLMClient(
        responses=[
            {
                "working_thesis": "Heat policy should be housing policy.",
                "sections": [
                    {
                        "heading": "Source-specific section",
                        "purpose": "build toward claim from concrete source detail",
                        "key_points": ["Use page-specific renter heat evidence."],
                        "note_ids": ["note_001"],
                        "target_words": 320,
                    }
                ],
            }
        ]
    )
    service = ThesisOutlineService(client)

    service.create_outline(
        job=EssayJob(id="job1", task_spec_id="task1", selected_topic_id="topic_001"),
        task_spec=TaskSpecification(id="task1", version=1, raw_text="Write 1000 words."),
        selected_topic=_selected_topic(),
        research_plan=_plan(),
        evidence_map=_evidence_map(),
        source_packets=[_source_packet()],
    )

    assert "STYLE-AWARE STRUCTURE" in client.calls[0]["system"]
    blocks = client.calls[0]["user_blocks"]
    assert blocks[0].cacheable is True
    context = json.loads(blocks[0].text)
    packet = context["source_packets"][0]
    assert packet["packet_id"] == "src1-pdf-pages-0002-0003"
    assert packet["source_id"] == "src1"
    assert packet["locator_type"] == "pdf_pages"
    assert packet["pdf_page_start"] == 2
    assert packet["pdf_page_end"] == 3
    assert packet["printed_page_start"] == "1"
    assert packet["printed_page_end"] == "2"
    assert packet["heading_path"] == ["Chapter 1", "Heat"]
    assert packet["extraction_method"] == "ocr"
    assert packet["text_quality"] == "partial"
    assert packet["warnings"] == ["low confidence"]
    assert packet["text"] == "Full source packet text for outlining."


def test_outline_warns_when_required_structure_clause_is_missing() -> None:
    """Q1: assignment requires sections like 'Methodology' and 'Discussion'.
    The outline must surface a warning when no section heading or purpose
    plausibly satisfies a required clause."""
    from essay_writer.outlining.schema import OutlineSection
    from essay_writer.outlining.service import validate_outline_coverage

    sections = [
        OutlineSection(
            id="section_001",
            heading="Introduction",
            purpose="introduce topic",
            note_ids=["note_001"],
        ),
        OutlineSection(
            id="section_002",
            heading="Methods Used",
            purpose="describe research methods",
            note_ids=["note_001"],
        ),
    ]
    task_spec = TaskSpecification(
        id="task1",
        version=1,
        raw_text="Required: include Methodology and Discussion.",
        required_structure=["Methodology", "Discussion"],
    )

    warnings = validate_outline_coverage(
        sections=sections,
        task_spec=task_spec,
        research_plan=_plan(),
        evidence_map=_evidence_map(),
    )

    assert any("Discussion" in w for w in warnings)
    assert not any("Methodology" in w for w in warnings), (
        "fuzzy match ('Methods Used' vs 'Methodology') should suppress this"
    )


def test_outline_warns_when_required_source_is_skipped() -> None:
    """Q7: research plan asks for a specific source, outline never cites it."""
    from essay_writer.outlining.schema import OutlineSection
    from essay_writer.outlining.service import validate_outline_coverage
    from essay_writer.sources.access_schema import SourceLocator

    sections = [
        OutlineSection(
            id="section_001",
            heading="Body",
            purpose="argue thesis",
            note_ids=["note_001"],  # only uses src1; src2 dropped
        )
    ]
    plan = ResearchPlan(
        id="research_plan_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        version=1,
        research_question="?",
        source_requirements=[],
        uploaded_source_priorities=[],
        expected_evidence_categories=[],
        source_requests=[
            SourceLocator(source_id="src1", locator_type="pdf_pages", pdf_page_start=1, pdf_page_end=1),
            SourceLocator(source_id="src2", locator_type="pdf_pages", pdf_page_start=1, pdf_page_end=1),
        ],
    )

    warnings = validate_outline_coverage(
        sections=sections,
        task_spec=TaskSpecification(id="task1", version=1, raw_text="x"),
        research_plan=plan,
        evidence_map=_evidence_map(),
    )

    assert any("src2" in w for w in warnings)
    assert not any("src1" in w for w in warnings)


def test_outline_warns_when_priority_high_source_is_skipped() -> None:
    """Q7: priority='high' uploaded source dropped from the outline is
    a separate (often louder) signal than a generic source_requests miss."""
    from essay_writer.outlining.schema import OutlineSection
    from essay_writer.outlining.service import validate_outline_coverage
    from essay_writer.research_planning.schema import SourceReadingPriority

    sections = [
        OutlineSection(
            id="section_001",
            heading="Body",
            purpose="argue thesis",
            note_ids=["note_001"],
        )
    ]
    plan = ResearchPlan(
        id="research_plan_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        version=1,
        research_question="?",
        source_requirements=[],
        uploaded_source_priorities=[
            SourceReadingPriority(source_id="src-primary", priority="high", rationale="primary"),
            SourceReadingPriority(source_id="src-secondary", priority="low", rationale="background"),
        ],
        expected_evidence_categories=[],
    )

    warnings = validate_outline_coverage(
        sections=sections,
        task_spec=TaskSpecification(id="task1", version=1, raw_text="x"),
        research_plan=plan,
        evidence_map=_evidence_map(),
    )

    assert any("src-primary" in w and "high" in w for w in warnings)
    assert not any("src-secondary" in w for w in warnings)


def _selected_topic() -> SelectedTopic:
    return SelectedTopic(
        job_id="job1",
        round_id="round1",
        topic_id="topic_001",
        title="Urban heat and housing",
        research_question="How does heat affect renters?",
        tentative_thesis_direction="Heat policy should be housing policy",
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        id="research_plan_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        version=1,
        research_question="How does heat affect renters?",
        source_requirements=["Use uploaded sources."],
        uploaded_source_priorities=[],
        expected_evidence_categories=["thesis_support"],
    )


def _evidence_map() -> EvidenceMap:
    note = ResearchNote(
        id="note_001",
        source_id="src1",
        chunk_id="chunk1",
        page_start=1,
        page_end=1,
        claim="Heat affects renters.",
        quote=None,
        paraphrase="Renters face heat risk.",
        relevance="Supports topic.",
        supports_topic=True,
        evidence_type="argument",
        confidence=0.8,
    )
    return EvidenceMap(
        id="evidence_map_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        research_question="How does heat affect renters?",
        thesis_direction="Heat policy should be housing policy",
        notes=[note],
        evidence_groups=[
            EvidenceGroup(
                id="group_001",
                label="Housing risk",
                purpose="thesis_support",
                note_ids=["note_001"],
                synthesis="Heat risk supports a housing-policy argument.",
            )
        ],
        gaps=[],
        conflicts=[],
    )


def _source_packet() -> SourceTextPacket:
    return SourceTextPacket(
        packet_id="src1-pdf-pages-0002-0003",
        source_id="src1",
        locator=SourceLocator(
            source_id="src1",
            locator_type="pdf_pages",
            pdf_page_start=2,
            pdf_page_end=3,
        ),
        text="Full source packet text for outlining.",
        pdf_page_start=2,
        pdf_page_end=3,
        printed_page_start="1",
        printed_page_end="2",
        heading_path=["Chapter 1", "Heat"],
        extraction_method="ocr",
        text_quality="partial",
        warnings=["low confidence"],
    )
