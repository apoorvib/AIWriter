from __future__ import annotations

import pytest

from essay_writer.jobs import EssayJobStore, EssayWorkflow, TopicSelectionError
from essay_writer.drafting.schema import EssayDraft
from essay_writer.research.schema import EvidenceMap, FinalTopicResearchResult, ResearchReport
from essay_writer.topic_ideation.schema import CandidateTopic, TopicIdeationResult, TopicSourceLead
from essay_writer.topic_ideation.storage import TopicRoundStore
from tests.task_spec._tmp import LocalTempDir


def test_workflow_records_topic_rounds_and_previous_candidates() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        workflow = EssayWorkflow(
            job_store,
            TopicRoundStore(tmp_path / "topic_store"),
        )
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        first = _result("task1", [_candidate("topic_001", "Urban heat and housing")])

        round_1 = workflow.record_topic_round(job_id=job.id, topic_result=first)
        previous = workflow.get_previous_candidates(job.id)
        second = _result("task1", [_candidate("topic_001", "Cooling centers and access")])
        round_2 = workflow.record_topic_round(
            job_id=job.id,
            topic_result=second,
            user_instruction="Give me more choices, but narrower.",
            previous_candidates=previous,
        )
        updated = job_store.load(job.id)

    assert round_1.round_number == 1
    assert round_1.previous_topic_ids == []
    assert round_2.round_number == 2
    assert round_2.user_instruction == "Give me more choices, but narrower."
    assert round_2.previous_topic_ids == ["topic_001"]
    assert updated.status == "topic_selection_ready"
    assert updated.current_stage == "topic_selection"
    assert updated.topic_round_ids == [round_1.id, round_2.id]


def test_workflow_attaches_task_and_sources_to_created_job() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        workflow = EssayWorkflow(job_store, TopicRoundStore(tmp_path / "topic_store"))
        job = workflow.create_job(job_id="job1")

        after_sources = workflow.attach_sources(job_id=job.id, source_ids=["src1", "src1", "src2"])
        after_task = workflow.attach_task_spec(job_id=job.id, task_spec_id="task1")

    assert after_sources.source_ids == ["src1", "src2"]
    assert after_sources.status == "created"
    assert after_sources.current_stage == "source_ingestion"
    assert after_task.status == "sources_ready"
    assert after_task.current_stage == "topic_ideation"
    assert after_task.task_spec_id == "task1"
    assert after_task.source_ids == ["src1", "src2"]


def test_workflow_marks_blocked_and_error_states() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        workflow = EssayWorkflow(job_store, TopicRoundStore(tmp_path / "topic_store"))
        job = workflow.create_job(job_id="job1")

        blocked = workflow.mark_blocked(job_id=job.id, stage="task_specification", message="Choose a prompt.")
        errored = workflow.mark_error(job_id=job.id, stage="source_ingestion", message="Source failed.")

    assert blocked.status == "blocked"
    assert blocked.current_stage == "task_specification"
    assert blocked.error_state is not None
    assert blocked.error_state.message == "Choose a prompt."
    assert errored.status == "error"
    assert errored.current_stage == "source_ingestion"
    assert errored.error_state is not None
    assert errored.error_state.message == "Source failed."


def test_topic_round_store_rejects_round_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(EssayJobStore(tmp_path / "essay_store"), topic_store)
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=_result("task1", [_candidate("topic_001", "Urban heat and housing")]),
        )

        with pytest.raises(FileExistsError):
            topic_store.save_round(round_)


def test_select_topic_persists_selection_and_allows_research_planning() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=_result("task1", [_candidate("topic_001", "Urban heat and housing")]),
        )

        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        ready = workflow.ensure_research_planning_ready(job.id)
        loaded_selected = topic_store.load_selected_topic(job.id)

    assert selected.topic_id == "topic_001"
    assert loaded_selected.round_id == round_.id
    assert ready.status == "research_planning_ready"
    assert ready.current_stage == "research_planning"
    assert ready.selected_topic_id == "topic_001"
    assert ready.selected_topic_round_id == round_.id


def test_reject_topic_persists_rejection_reason() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=_result("task1", [_candidate("topic_001", "Urban heat and housing")]),
        )

        rejected = workflow.reject_topic(
            job_id=job.id,
            round_number=round_.round_number,
            topic_id="topic_001",
            reason="Too broad.",
        )
        loaded = workflow.get_rejected_topics(job.id)

    assert rejected.reason == "Too broad."
    assert loaded == [rejected]


def test_research_planning_requires_selected_topic() -> None:
    with LocalTempDir() as tmp_path:
        workflow = EssayWorkflow(
            EssayJobStore(tmp_path / "essay_store"),
            TopicRoundStore(tmp_path / "topic_store"),
        )
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        workflow.record_topic_round(
            job_id=job.id,
            topic_result=_result("task1", [_candidate("topic_001", "Urban heat and housing")]),
        )

        with pytest.raises(TopicSelectionError, match="selected topic"):
            workflow.ensure_research_planning_ready(job.id)


def test_select_topic_rejects_unknown_topic_id() -> None:
    with LocalTempDir() as tmp_path:
        workflow = EssayWorkflow(
            EssayJobStore(tmp_path / "essay_store"),
            TopicRoundStore(tmp_path / "topic_store"),
        )
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        workflow.record_topic_round(
            job_id=job.id,
            topic_result=_result("task1", [_candidate("topic_001", "Urban heat and housing")]),
        )

        with pytest.raises(TopicSelectionError, match="Topic id not found"):
            workflow.select_topic(job_id=job.id, round_number=1, topic_id="missing")


def test_workflow_records_research_draft_and_validation_stages() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        workflow = EssayWorkflow(job_store, TopicRoundStore(tmp_path / "topic_store"))
        job = workflow.create_job(job_id="job1", task_spec_id="task1", source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=_result("task1", [_candidate("topic_001", "Urban heat and housing")]),
        )
        workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")

        research_job = workflow.record_research_complete(
            job_id=job.id,
            research_result=_research_result(job.id, "topic_001"),
        )
        draft_job = workflow.record_draft_ready(
            job_id=job.id,
            draft=EssayDraft(
                id="draft1",
                job_id=job.id,
                version=1,
                selected_topic_id="topic_001",
                content="Draft.",
            ),
        )
        final_job = workflow.record_validation_complete(
            job_id=job.id,
            validation_report_id="draft1:v001",
            passes=True,
        )

    assert research_job.status == "drafting_ready"
    assert research_job.evidence_map_id == "evidence_map_v001"
    assert draft_job.status == "validation_ready"
    assert draft_job.draft_id == "draft1"
    assert final_job.status == "validation_complete"
    assert final_job.current_stage == "complete"
    assert final_job.validation_report_id == "draft1:v001"


def _result(task_spec_id: str, candidates: list[CandidateTopic]) -> TopicIdeationResult:
    return TopicIdeationResult(task_spec_id=task_spec_id, candidates=candidates)


def _candidate(topic_id: str, title: str) -> CandidateTopic:
    return CandidateTopic(
        id=topic_id,
        title=title,
        research_question=f"What should we argue about {title}?",
        tentative_thesis_direction=f"{title} can support a focused policy argument.",
        rationale="Source manifests indicate enough coverage.",
        source_leads=[
            TopicSourceLead(
                source_id="src1",
                chunk_ids=["src1-chunk-0001"],
                suggested_source_search_queries=["housing heat"],
            )
        ],
        fit_score=0.8,
        evidence_score=0.8,
        originality_score=0.7,
    )


def _research_result(job_id: str, topic_id: str) -> FinalTopicResearchResult:
    evidence_map = EvidenceMap(
        id="evidence_map_v001",
        job_id=job_id,
        selected_topic_id=topic_id,
        research_question="Question?",
        thesis_direction="Thesis.",
        notes=[],
    )
    return FinalTopicResearchResult(
        evidence_map=evidence_map,
        report=ResearchReport(
            job_id=job_id,
            selected_topic_id=topic_id,
            evidence_map_id=evidence_map.id,
            note_count=0,
            source_count=0,
        ),
    )
