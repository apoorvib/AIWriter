from __future__ import annotations

import pytest

from essay_writer.jobs.schema import EssayJob
from essay_writer.research_planning.service import ResearchPlanningService
from essay_writer.sources.access_schema import SourceAccessConfig, SourceLocator
from essay_writer.sources.map import build_source_map
from essay_writer.sources.schema import SourceDocument, SourcePage
from essay_writer.sources.schema import SourceIndexManifest
from essay_writer.task_spec.schema import ChecklistItem, TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic, TopicSourceLead


def test_research_plan_prioritizes_uploaded_source_leads_and_keeps_external_queries_gated() -> None:
    plan = ResearchPlanningService().create_plan(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        index_manifests=[_manifest()],
    )

    assert plan.id == "research_plan_v001"
    assert plan.job_id == "job1"
    assert plan.selected_topic_id == "topic_001"
    assert plan.uploaded_source_priorities[0].source_id == "src1"
    assert plan.uploaded_source_priorities[0].priority == "high"
    assert plan.uploaded_source_priorities[0].chunk_ids == ["src1-chunk-0001"]
    assert "Use at least two uploaded sources." in plan.source_requirements
    assert "counterargument" in plan.expected_evidence_categories
    assert plan.external_search_allowed is False
    assert plan.external_search_queries == []


def test_research_plan_fills_external_queries_only_when_allowed() -> None:
    plan = ResearchPlanningService().create_plan(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=_selected_topic(),
        index_manifests=[_manifest()],
        external_search_allowed=True,
    )

    assert plan.external_search_allowed is True
    assert plan.external_search_queries


def test_research_plan_schema_rejects_external_queries_without_permission() -> None:
    with pytest.raises(ValueError, match="external_search_allowed"):
        from essay_writer.research_planning.schema import ResearchPlan

        ResearchPlan(
            id="research_plan_v001",
            job_id="job1",
            selected_topic_id="topic_001",
            version=1,
            research_question="Question?",
            source_requirements=[],
            uploaded_source_priorities=[],
            expected_evidence_categories=[],
            external_search_allowed=False,
            external_search_queries=["not allowed"],
        )


def test_research_plan_validates_selected_topic_source_requests() -> None:
    selected = _selected_topic(
        source_requests=[
            SourceLocator(
                source_id="src1",
                locator_type="pdf_pages",
                pdf_page_start=2,
                pdf_page_end=3,
                reason="Relevant pages.",
            )
        ]
    )
    source_map = build_source_map(
        _source("src1"),
        [
            SourcePage("src1", 1, "front", 5, "pypdf"),
            SourcePage("src1", 2, "page two text", 13, "pypdf"),
            SourcePage("src1", 3, "page three text", 15, "pypdf"),
        ],
    )

    plan = ResearchPlanningService().create_plan(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=selected,
        index_manifests=[],
        source_maps=[source_map],
    )

    assert plan.source_requests == selected.source_requests


def test_research_plan_drops_oversized_source_requests() -> None:
    selected = _selected_topic(
        source_requests=[
            SourceLocator(
                source_id="src1",
                locator_type="pdf_pages",
                pdf_page_start=1,
                pdf_page_end=5,
                reason="Too much.",
            )
        ]
    )
    source_map = build_source_map(
        _source("src1"),
        [SourcePage("src1", page, f"page {page}", 6, "pypdf") for page in range(1, 6)],
    )

    plan = ResearchPlanningService().create_plan(
        job=_job(),
        task_spec=_task_spec(),
        selected_topic=selected,
        index_manifests=[],
        source_maps=[source_map],
        source_access_config=SourceAccessConfig(max_pdf_pages_per_request=2),
    )

    assert plan.source_requests == []
    assert any("oversized PDF page request" in warning for warning in plan.warnings)


def _job() -> EssayJob:
    return EssayJob(id="job1", task_spec_id="task1", source_ids=["src1"], selected_topic_id="topic_001")


def _task_spec() -> TaskSpecification:
    return TaskSpecification(
        id="task1",
        version=1,
        raw_text="Write an essay.",
        required_structure=["Include a counterargument."],
        extracted_checklist=[
            ChecklistItem(
                id="req_001",
                text="Use at least two uploaded sources.",
                category="source",
                required=True,
                source_span="Use at least two uploaded sources.",
                confidence=0.9,
            )
        ],
    )


def _selected_topic(source_requests: list[SourceLocator] | None = None) -> SelectedTopic:
    return SelectedTopic(
        job_id="job1",
        round_id="round1",
        topic_id="topic_001",
        title="Urban heat and housing",
        research_question="How does heat affect renters?",
        tentative_thesis_direction="Heat policy should be housing policy.",
        source_leads=[
            TopicSourceLead(
                source_id="src1",
                chunk_ids=["src1-chunk-0001"],
                suggested_source_search_queries=["renters heat"],
            )
        ],
        source_requests=source_requests or [],
    )


def _source(source_id: str) -> SourceDocument:
    return SourceDocument(
        id=source_id,
        original_path=f"{source_id}.pdf",
        file_name=f"{source_id}.pdf",
        source_type="pdf",
        page_count=5,
        char_count=100,
        extraction_method="pypdf",
        text_quality="readable",
        full_text_available=True,
        indexed=False,
    )


def _manifest() -> SourceIndexManifest:
    return SourceIndexManifest(
        source_id="src1",
        index_path="index.sqlite",
        total_chunks=3,
        total_chars=1000,
        entries=[],
    )
