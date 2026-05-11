from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.sources.access_schema import SourceMap, SourceUnit
from essay_writer.sources.schema import (
    SourceCard,
    SourceChunk,
    SourceDocument,
    SourceIndexEntry,
    SourceIndexManifest,
    SourceMaterializationResult,
    SourcePage,
)
from essay_writer.task_spec.schema import TaskSpecification
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent


def test_create_research_plan_and_commit_research_notes_validates_quotes() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_with_selected_topic(
            facade,
            source_text="Cooling access is uneven in rental housing.",
        )

        plan_result = facade.create_research_plan(job_id="job1")
        bundle_result = facade.resolve_source_requests(
            job_id="job1",
            research_plan_id=str(plan_result.data["research_plan_id"]),
        )
        packet_id = str(bundle_result.data["packet_ids"][0])
        prepared = facade.prepare_research_notes(
            job_id="job1",
            source_packet_bundle_id=str(bundle_result.data["source_packet_bundle_id"]),
        )
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_research_payload(packet_id=packet_id, quote="Cooling access is uneven"),
            producer=main_agent(),
        )
        committed = facade.commit_research_notes(
            work_result_id=str(submitted.data["work_result_id"])
        )
        research = facade.stores.research_store.load_latest("job1")

    assert plan_result.ok is True
    assert plan_result.data["research_plan_id"] == "research_plan_v001"
    assert plan_result.data["next_suggested_tools"] == ["resolve_source_requests"]
    assert bundle_result.data["packet_ids"] == [packet_id]
    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_research_notes"
    assert prepared.data["delegation"]["allowed_tools"] == ["submit_work_result"]
    assert committed.ok is True
    assert committed.data["evidence_map_id"] == "evidence_map_v001"
    assert committed.data["next_suggested_tools"] == ["prepare_outline"]
    assert research.evidence_map.notes[0].quote == "Cooling access is uneven"


def test_commit_research_notes_drops_absent_quote_with_warning() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_with_selected_topic(
            facade,
            source_text="Cooling access is uneven in rental housing.",
        )
        plan_result = facade.create_research_plan(job_id="job1")
        bundle_result = facade.resolve_source_requests(
            job_id="job1",
            research_plan_id=str(plan_result.data["research_plan_id"]),
        )
        packet_id = str(bundle_result.data["packet_ids"][0])
        prepared = facade.prepare_research_notes(
            job_id="job1",
            source_packet_bundle_id=str(bundle_result.data["source_packet_bundle_id"]),
        )
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_research_payload(packet_id=packet_id, quote="This quote is absent."),
            producer=main_agent(),
        )

        committed = facade.commit_research_notes(
            work_result_id=str(submitted.data["work_result_id"])
        )
        research = facade.stores.research_store.load_latest("job1")

    assert committed.ok is True
    assert research.evidence_map.notes[0].quote is None
    assert any("not found in chunk" in warning for warning in committed.warnings)


def _seed_job_with_selected_topic(
    facade: AgentToolFacade,
    *,
    source_text: str,
) -> None:
    facade.stores.task_store.save(
        TaskSpecification(
            id="task1",
            version=1,
            raw_text="Write a policy essay about climate adaptation.",
            assignment_title="Climate Adaptation Essay",
            source_document_ids=["src1"],
        )
    )
    _seed_source(facade, source_text=source_text)
    created = facade.create_job_from_artifacts("task1", ["src1"], job_id="job1")
    assert created.ok is True
    prepared = facade.prepare_topics("job1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload=_topic_payload(),
        producer=main_agent(),
    )
    committed = facade.commit_topics(work_result_id=str(submitted.data["work_result_id"]))
    assert committed.ok is True
    selected = facade.select_topic("job1", round_number=1, topic_id="topic_001")
    assert selected.ok is True


def _seed_source(facade: AgentToolFacade, *, source_text: str) -> None:
    facade.stores.source_store.save_materialized_source(
        SourceMaterializationResult(
            source=SourceDocument(
                id="src1",
                original_path="src1.pdf",
                file_name="src1.pdf",
                source_type="pdf",
                page_count=1,
                char_count=len(source_text),
                extraction_method="pypdf",
                text_quality="readable",
                full_text_available=True,
                indexed=True,
            ),
            pages=[
                SourcePage(
                    source_id="src1",
                    page_number=1,
                    text=source_text,
                    char_count=len(source_text),
                    extraction_method="pypdf",
                )
            ],
            chunks=[
                SourceChunk(
                    id="src1-chunk-001",
                    source_id="src1",
                    ordinal=1,
                    page_start=1,
                    page_end=1,
                    text=source_text,
                    char_count=len(source_text),
                )
            ],
            indexed=True,
            full_text_available=True,
            index_manifest=SourceIndexManifest(
                source_id="src1",
                index_path="internal.sqlite",
                total_chunks=1,
                total_chars=len(source_text),
                entries=[
                    SourceIndexEntry(
                        chunk_id="src1-chunk-001",
                        ordinal=1,
                        page_start=1,
                        page_end=1,
                        char_count=len(source_text),
                        heading="Cooling",
                        preview=source_text,
                    )
                ],
            ),
            source_map=SourceMap(
                source_id="src1",
                source_type="pdf",
                units=[
                    SourceUnit(
                        source_id="src1",
                        unit_id="page-1",
                        unit_type="pdf_page",
                        title="Cooling",
                        pdf_page_start=1,
                        pdf_page_end=1,
                        text=source_text,
                        char_count=len(source_text),
                        extraction_method="pypdf",
                        text_quality="readable",
                        preview=source_text,
                    )
                ],
            ),
            warnings=[],
        )
    )
    facade.stores.source_store.save_source_card(
        "src1",
        SourceCard(
            source_id="src1",
            title="Cooling Access Report",
            source_type="pdf",
            page_count=1,
            extraction_method="pypdf",
            brief_summary="Evidence about cooling access and rental housing.",
            key_topics=["cooling access", "housing"],
            useful_for_topic_ideation=["Supports a policy argument about renters."],
        ),
    )


def _topic_payload() -> dict[str, object]:
    return {
        "blocking_questions": [],
        "warnings": [],
        "candidates": [
            {
                "title": "Cooling access and housing inequality",
                "research_question": "How does cooling access expose housing inequality?",
                "tentative_thesis_direction": "Cooling access policy should be treated as housing policy.",
                "rationale": "The source card and manifest identify renter-focused cooling access evidence.",
                "parent_topic_id": None,
                "novelty_note": "Connects adaptation infrastructure to tenant protections.",
                "source_leads": [
                    {
                        "source_id": "src1",
                        "chunk_ids": ["src1-chunk-001"],
                        "suggested_source_search_queries": ["cooling access rental housing"],
                    }
                ],
                "source_requests": [
                    {
                        "source_id": "src1",
                        "locator_type": "pdf_pages",
                        "pdf_page_start": 1,
                        "pdf_page_end": 1,
                        "printed_page_label": None,
                        "section_id": None,
                        "query": None,
                        "chunk_id": None,
                        "reason": "Opening page has the relevant evidence.",
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


def _research_payload(*, packet_id: str, quote: str | None) -> dict[str, object]:
    return {
        "notes": [
            {
                "source_id": "src1",
                "chunk_id": packet_id,
                "page_start": 1,
                "page_end": 1,
                "claim": "Cooling access is uneven.",
                "quote": quote,
                "paraphrase": "The source frames cooling as unevenly available.",
                "relevance": "Supports the selected topic.",
                "supports_topic": True,
                "evidence_type": "argument",
                "tags": ["cooling"],
                "confidence": 0.8,
            }
        ],
        "evidence_groups": [
            {
                "label": "Cooling access",
                "purpose": "thesis_support",
                "note_ids": ["note_001"],
                "synthesis": "Cooling access supports the housing-policy thesis.",
            }
        ],
        "gaps": [],
        "conflicts": [],
        "warnings": [],
    }
