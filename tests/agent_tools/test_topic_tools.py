from __future__ import annotations

from dataclasses import replace

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


def test_prepare_submit_commit_and_select_topic_happy_path_with_recovery_refs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        run = facade.start_agent_run(objective="Choose topic.", job_id="job1")
        agent_run_id = str(run.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)

        prepared = facade.prepare_topics(
            "job1",
            user_instruction="Prefer a housing-policy angle.",
            max_candidates=4,
            agent_run_id=agent_run_id,
        )
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_topic_payload(),
            producer=main_agent(),
            agent_run_id=agent_run_id,
        )
        committed = facade.commit_topics(
            work_result_id=str(submitted.data["work_result_id"]),
            agent_run_id=agent_run_id,
        )
        selected = facade.select_topic(
            "job1",
            round_number=1,
            topic_id="topic_001",
            user_selection_evidence="User selected topic_001 after seeing the topic options.",
            agent_run_id=agent_run_id,
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert "prepare_topics" in facade.get_harness_instructions().data["currently_callable_tools"]
    assert prepared.ok is True
    assert prepared.data["stage"] == "topic_ideation"
    assert prepared.data["commit_tool"] == "commit_topics"
    assert prepared.data["delegation"]["recommended"] is False
    assert prepared.data["delegation"]["reason"] == "topic selection is a global planning step"
    assert prepared.data["next_suggested_tools"] == ["submit_work_result"]
    assert len(prepared.data["prompt_blocks"]) == 2
    assert prepared.data["prompt_blocks"][0]["cacheable"] is True
    assert prepared.data["prompt_blocks"][1]["cacheable"] is False
    assert submitted.data["next_suggested_tools"] == ["commit_topics"]
    assert committed.ok is True
    assert committed.data["round_number"] == 1
    assert committed.data["candidate_topic_ids"] == ["topic_001"]
    assert committed.data["requires_user_topic_selection"] is True
    assert committed.data["candidate_topics"][0]["id"] == "topic_001"
    assert committed.data["next_suggested_tools"] == ["select_topic", "reject_topic"]
    assert selected.ok is True
    assert selected.data["selected_topic_id"] == "topic_001"
    assert selected.data["selected_topic"]["title"] == "Cooling access and housing inequality"
    assert selected.data["next_suggested_tools"] == ["create_research_plan"]
    assert recovered.data["committed_artifact_refs"]["selected_topic_id"] == "topic_001"
    assert recovered.data["committed_artifact_refs"]["job_id"] == "job1"
    assert recovered.data["next_suggested_tools"] == ["create_research_plan"]


def test_select_topic_requires_user_selection_evidence() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        prepared = facade.prepare_topics("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_topic_payload(),
            producer=main_agent(),
        )
        committed = facade.commit_topics(work_result_id=str(submitted.data["work_result_id"]))

        selected = facade.select_topic("job1", round_number=1, topic_id="topic_001")

    assert committed.ok is True
    assert selected.ok is False
    assert selected.error is not None
    assert selected.error.code == "topic_selection_user_confirmation_required"
    assert selected.next_suggested_tools == ["select_topic", "reject_topic"]


def test_commit_topics_with_blocking_questions_does_not_record_round() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        run = facade.start_agent_run(objective="Choose topic.", job_id="job1")
        agent_run_id = str(run.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        prepared = facade.prepare_topics("job1", agent_run_id=agent_run_id)
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "blocking_questions": ["Which assigned prompt should this answer?"],
                "warnings": [],
                "candidates": [],
            },
            producer=main_agent(),
            agent_run_id=agent_run_id,
        )

        committed = facade.commit_topics(
            work_result_id=str(submitted.data["work_result_id"]),
            agent_run_id=agent_run_id,
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert committed.ok is True
    assert committed.data["blocking_questions"] == ["Which assigned prompt should this answer?"]
    assert committed.data["candidate_topic_ids"] == []
    assert committed.data["topic_round_id"] is None
    assert committed.data["next_suggested_tools"] == ["prepare_topics"]
    assert facade.stores.topic_store.list_rounds("job1") == []
    assert recovered.data["status"] == "blocked"
    assert recovered.data["current_phase"] == "topic_ideation"
    assert recovered.data["next_suggested_tools"] == ["prepare_topics"]


def test_commit_topics_retry_same_result_is_idempotent() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        prepared = facade.prepare_topics("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_topic_payload(),
            producer=main_agent(),
        )
        work_result_id = str(submitted.data["work_result_id"])

        first = facade.commit_topics(work_result_id=work_result_id)
        second = facade.commit_topics(work_result_id=work_result_id)
        round_count = len(facade.stores.topic_store.list_rounds("job1"))

    assert first.ok is True
    assert second.ok is True
    assert first.data["topic_round_id"] == second.data["topic_round_id"]
    assert second.data["already_committed"] is True
    assert round_count == 1


def test_commit_topics_different_same_ordinal_results_create_new_rounds() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        prepared_first = facade.prepare_topics("job1", user_instruction="Keep it practical.")
        submitted_first = facade.submit_work_result(
            str(prepared_first.data["work_packet_id"]),
            payload=_topic_payload(title="Cooling access and housing inequality"),
            producer=main_agent(),
        )
        prepared_second = facade.prepare_topics("job1", user_instruction="Keep it practical.")
        submitted_second = facade.submit_work_result(
            str(prepared_second.data["work_packet_id"]),
            payload=_topic_payload(title="Heat standards for rental housing"),
            producer=main_agent(),
        )

        first = facade.commit_topics(work_result_id=str(submitted_first.data["work_result_id"]))
        second = facade.commit_topics(work_result_id=str(submitted_second.data["work_result_id"]))
        rounds = facade.stores.topic_store.list_rounds("job1")

    assert first.ok is True
    assert second.ok is True
    assert len(rounds) == 2
    assert rounds[0].candidates[0].id == "topic_001"
    assert rounds[1].candidates[0].id == "topic_001"
    assert rounds[1].candidates[0].title == "Heat standards for rental housing"


def test_commit_topics_direct_payload_requires_ready_job_before_writing_artifacts() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        facade.stores.task_store.save(
            TaskSpecification(
                id="task1",
                version=1,
                raw_text="Write a policy essay about climate adaptation.",
                assignment_title="Climate Adaptation Essay",
                source_document_ids=[],
            )
        )
        facade.stores.workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=[])

        committed = facade.commit_topics(job_id="job1", payload=_topic_payload())

    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "job_sources_missing"
    assert facade.work_store.list_packets() == []
    assert facade.work_store.list_results() == []


def test_commit_topics_rejects_malformed_packet_max_candidates_context() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        prepared = facade.prepare_topics("job1")
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
        facade.work_store.save_packet(
            replace(packet, context={**packet.context, "max_candidates": "many"})
        )
        submitted = facade.submit_work_result(
            packet.work_packet_id,
            payload=_topic_payload(),
            producer=main_agent(),
        )

        committed = facade.commit_topics(work_result_id=str(submitted.data["work_result_id"]))

    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "invalid_max_candidates"


def test_reject_topic_records_rejection_and_suggests_next_topic_tools() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_ready_job(facade)
        prepared = facade.prepare_topics("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_topic_payload(),
            producer=main_agent(),
        )
        facade.commit_topics(work_result_id=str(submitted.data["work_result_id"]))

        rejected = facade.reject_topic("job1", round_number=1, topic_id="topic_001", reason="Too broad.")

    assert rejected.ok is True
    assert rejected.data["rejected_topic_id"] == "job1-topic-round-001:topic_001"
    assert rejected.data["topic_id"] == "topic_001"
    assert rejected.data["next_suggested_tools"] == ["prepare_topics", "select_topic"]


def _seed_ready_job(facade: AgentToolFacade) -> None:
    facade.stores.task_store.save(
        TaskSpecification(
            id="task1",
            version=1,
            raw_text="Write a policy essay about climate adaptation.",
            assignment_title="Climate Adaptation Essay",
            source_document_ids=["src1"],
        )
    )
    _seed_source(facade)
    created = facade.create_job_from_artifacts("task1", ["src1"], job_id="job1")
    assert created.ok is True


def _seed_source(facade: AgentToolFacade) -> None:
    text = "Cooling access appears in rental housing policy debates."
    facade.stores.source_store.save_materialized_source(
        SourceMaterializationResult(
            source=SourceDocument(
                id="src1",
                original_path="src1.pdf",
                file_name="src1.pdf",
                source_type="pdf",
                page_count=1,
                char_count=len(text),
                extraction_method="pypdf",
                text_quality="readable",
                full_text_available=True,
                indexed=True,
            ),
            pages=[
                SourcePage(
                    source_id="src1",
                    page_number=1,
                    text=text,
                    char_count=len(text),
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
                    text=text,
                    char_count=len(text),
                )
            ],
            indexed=True,
            full_text_available=True,
            index_manifest=SourceIndexManifest(
                source_id="src1",
                index_path="internal.sqlite",
                total_chunks=1,
                total_chars=len(text),
                entries=[
                    SourceIndexEntry(
                        chunk_id="src1-chunk-001",
                        ordinal=1,
                        page_start=1,
                        page_end=1,
                        char_count=len(text),
                        heading="Cooling",
                        preview=text,
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
                        text=text,
                        char_count=len(text),
                        extraction_method="pypdf",
                        text_quality="readable",
                        preview=text,
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


def _topic_payload(
    *,
    title: str = "Cooling access and housing inequality",
    research_question: str = "How does cooling access expose housing inequality?",
) -> dict[str, object]:
    return {
        "blocking_questions": [],
        "warnings": ["Check evidence depth before drafting."],
        "candidates": [
            {
                "title": title,
                "research_question": research_question,
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
