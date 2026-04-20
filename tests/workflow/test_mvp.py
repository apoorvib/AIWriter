from __future__ import annotations

import pytest

from llm.mock import MockLLMClient
from essay_writer.drafting.revision import DraftRevisionService
from essay_writer.drafting.service import DraftService
from essay_writer.drafting.storage import DraftStore
from essay_writer.exporting.service import FinalExportService
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.jobs import EssayJobStore, EssayWorkflow
from essay_writer.outlining.service import ThesisOutlineService
from essay_writer.outlining.storage import ThesisOutlineStore
from essay_writer.research.service import FinalTopicResearchService
from essay_writer.research.storage import ResearchStore
from essay_writer.research_planning.service import ResearchPlanningService
from essay_writer.research_planning.storage import ResearchPlanStore
from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.schema import SourceCard, SourceChunk, SourceDocument, SourceIngestionResult
from essay_writer.sources.storage import SourceStore
from essay_writer.task_spec.schema import ChecklistItem, TaskSpecification
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.retrieval import TopicEvidenceRetriever
from essay_writer.topic_ideation.schema import CandidateTopic, SelectedTopic, TopicIdeationResult, TopicSourceLead
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.validation.service import ValidationService
from essay_writer.validation.storage import ValidationStore
from essay_writer.workflow.mvp import InsufficientEvidenceError, MvpWorkflowRunner, WorkflowContractError
from tests.task_spec._tmp import LocalTempDir


def test_mvp_workflow_runs_from_selected_topic_through_validation() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")
        export_store = FinalExportStore(tmp_path / "export_store")

        task_spec = _task_spec()
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(
                task_spec_id=task_spec.id,
                candidates=[_candidate()],
            ),
        )
        selected = workflow.select_topic(
            job_id=job.id,
            round_number=round_.round_number,
            topic_id="topic_001",
        )
        manifest = _save_source(source_store)

        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(MockLLMClient(responses=[_research_response()])),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(MockLLMClient(responses=[_draft_response()])),
            draft_store=draft_store,
            validation_service=ValidationService(MockLLMClient(responses=[_validation_response()])),
            validation_store=validation_store,
            export_service=FinalExportService(),
            export_store=export_store,
            source_store=source_store,
        )

        result = runner.run_after_topic_selection(
            job_id=job.id,
            task_spec=task_spec,
            selected_topic=selected,
            index_manifests=[manifest],
        )
        loaded_research = research_store.load_latest(job.id)
        loaded_research_plan = research_plan_store.load_latest(job.id)
        loaded_outline = outline_store.load_latest(job.id)
        loaded_draft = draft_store.load_latest(job.id)
        loaded_validation = validation_store.load_latest(job.id)
        loaded_export = export_store.load_latest(job.id)
        final_job = job_store.load(job.id)

    assert result.retrieved_evidence.chunks[0].chunk_id == "src1-chunk-0001"
    assert result.research_plan.id == "research_plan_v001"
    assert result.research.evidence_map.notes[0].id == "note_001"
    assert result.outline.id == "thesis_outline_v001"
    assert result.draft.content.startswith("Urban heat")
    assert result.validation.passes is True
    assert result.final_export is not None
    assert result.final_export.id == "final_export_001"
    assert loaded_research_plan.id == result.research_plan.id
    assert loaded_research.evidence_map.id == "evidence_map_v001"
    assert loaded_outline.id == result.outline.id
    assert loaded_draft.id == result.draft.id
    assert loaded_draft.outline_id == loaded_outline.id
    assert loaded_validation.draft_id == result.draft.id
    assert loaded_validation.metadata_citation_warnings[0].source_id == "src1"
    assert loaded_export.draft_id == result.draft.id
    assert "# Final Essay" in loaded_export.content
    assert final_job.status == "validation_complete"
    assert final_job.current_stage == "complete"
    assert final_job.research_plan_id == "research_plan_v001"
    assert final_job.evidence_map_id == "evidence_map_v001"
    assert final_job.outline_id == "thesis_outline_v001"
    assert final_job.draft_id == result.draft.id
    assert final_job.validation_report_id == f"{result.draft.id}:v001"
    assert final_job.final_export_id == "final_export_001"


def test_mvp_preflight_rejects_mismatched_task_before_llm_calls() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")

        task_spec = _task_spec()
        bad_task_spec = TaskSpecification(id="wrong-task", version=1, raw_text="Wrong.")
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(task_spec_id=task_spec.id, candidates=[_candidate()]),
        )
        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        manifest = _save_source(source_store)
        research_client = MockLLMClient(responses=[_research_response()])
        draft_client = MockLLMClient(responses=[_draft_response()])
        validation_client = MockLLMClient(responses=[_validation_response()])
        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(research_client),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(draft_client),
            draft_store=draft_store,
            validation_service=ValidationService(validation_client),
            validation_store=validation_store,
        )

        with pytest.raises(WorkflowContractError):
            runner.run_after_topic_selection(
                job_id=job.id,
                task_spec=bad_task_spec,
                selected_topic=selected,
                index_manifests=[manifest],
            )
        loaded_job = job_store.load(job.id)

    assert research_client.calls == []
    assert draft_client.calls == []
    assert validation_client.calls == []
    assert loaded_job.status == "error"
    assert loaded_job.error_state is not None
    assert "Task spec id mismatch" in loaded_job.error_state.message


def test_mvp_blocks_when_selected_topic_has_no_retrieved_evidence() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")

        task_spec = _task_spec()
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        no_leads = CandidateTopic(
            id="topic_001",
            title="Unsupported topic",
            research_question="What if no source supports this?",
            tentative_thesis_direction="This should not draft.",
            rationale="No evidence.",
            source_leads=[],
        )
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(task_spec_id=task_spec.id, candidates=[no_leads]),
        )
        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        manifest = _save_source(source_store)
        research_client = MockLLMClient(responses=[])
        draft_client = MockLLMClient(responses=[_draft_response()])
        validation_client = MockLLMClient(responses=[_validation_response()])
        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(research_client),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(draft_client),
            draft_store=draft_store,
            validation_service=ValidationService(validation_client),
            validation_store=validation_store,
        )

        with pytest.raises(InsufficientEvidenceError):
            runner.run_after_topic_selection(
                job_id=job.id,
                task_spec=task_spec,
                selected_topic=selected,
                index_manifests=[manifest],
            )
        loaded_job = job_store.load(job.id)
        research = research_store.load_latest(job.id)

    assert research_client.calls == []
    assert draft_client.calls == []
    assert validation_client.calls == []
    assert research.evidence_map.notes == []
    assert loaded_job.status == "blocked"
    assert loaded_job.current_stage == "research"
    assert loaded_job.error_state is not None
    assert "not have enough" in loaded_job.error_state.message


def test_run_selected_job_resumes_from_persisted_drafting_ready_state() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        task_store = TaskSpecStore(tmp_path / "task_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")

        task_spec = _task_spec()
        task_store.save(task_spec)
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(task_spec_id=task_spec.id, candidates=[_candidate()]),
        )
        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        manifest = _save_source(source_store)
        retrieved = TopicEvidenceRetriever(source_store).retrieve_for_selected_topic(
            selected,
            index_manifests=[manifest],
        )
        research_plan = ResearchPlanningService().create_plan(
            job=job_store.load(job.id),
            task_spec=task_spec,
            selected_topic=selected,
            index_manifests=[manifest],
        )
        research_plan_store.save(research_plan)
        workflow.record_research_plan_complete(job_id=job.id, research_plan=research_plan)
        research = FinalTopicResearchService(MockLLMClient(responses=[_research_response()])).extract(
            job=job_store.load(job.id),
            task_spec=task_spec,
            selected_topic=selected,
            retrieved_evidence=[retrieved],
        )
        research_store.save_result(research, version=1)
        workflow.record_research_complete(job_id=job.id, research_result=research)

        resume_research_client = MockLLMClient(responses=[])
        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(resume_research_client),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(MockLLMClient(responses=[_draft_response()])),
            draft_store=draft_store,
            validation_service=ValidationService(MockLLMClient(responses=[_validation_response()])),
            validation_store=validation_store,
            task_store=task_store,
            topic_store=topic_store,
            source_store=source_store,
        )

        result = runner.run_selected_job(job.id)

    assert resume_research_client.calls == []
    assert result.job.status == "validation_complete"
    assert result.research.evidence_map.id == "evidence_map_v001"
    assert result.draft.version == 1
    assert result.validation.draft_id == result.draft.id


def test_mvp_records_stage_error_when_drafting_fails() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")

        task_spec = _task_spec()
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(task_spec_id=task_spec.id, candidates=[_candidate()]),
        )
        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        manifest = _save_source(source_store)
        validation_client = MockLLMClient(responses=[_validation_response()])
        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(MockLLMClient(responses=[_research_response()])),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(MockLLMClient(responses=[])),
            draft_store=draft_store,
            validation_service=ValidationService(validation_client),
            validation_store=validation_store,
        )

        with pytest.raises(RuntimeError, match="ran out"):
            runner.run_after_topic_selection(
                job_id=job.id,
                task_spec=task_spec,
                selected_topic=selected,
                index_manifests=[manifest],
            )
        loaded_job = job_store.load(job.id)

    assert loaded_job.status == "error"
    assert loaded_job.current_stage == "drafting"
    assert loaded_job.error_state is not None
    assert "ran out" in loaded_job.error_state.message
    assert validation_client.calls == []


def test_run_selected_job_resumes_validation_ready_and_writes_next_validation_version() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        task_store = TaskSpecStore(tmp_path / "task_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")

        task_spec = _task_spec()
        task_store.save(task_spec)
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(task_spec_id=task_spec.id, candidates=[_candidate()]),
        )
        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        manifest = _save_source(source_store)
        retrieved = TopicEvidenceRetriever(source_store).retrieve_for_selected_topic(
            selected,
            index_manifests=[manifest],
        )
        research_plan = ResearchPlanningService().create_plan(
            job=job_store.load(job.id),
            task_spec=task_spec,
            selected_topic=selected,
            index_manifests=[manifest],
        )
        research_plan_store.save(research_plan)
        workflow.record_research_plan_complete(job_id=job.id, research_plan=research_plan)
        research = FinalTopicResearchService(MockLLMClient(responses=[_research_response()])).extract(
            job=job_store.load(job.id),
            task_spec=task_spec,
            selected_topic=selected,
            retrieved_evidence=[retrieved],
        )
        research_store.save_result(research, version=1)
        job = workflow.record_research_complete(job_id=job.id, research_result=research)
        outline = _outline_service().create_outline(
            job=job,
            task_spec=task_spec,
            selected_topic=selected,
            research_plan=research_plan,
            evidence_map=research.evidence_map,
        )
        outline_store.save(outline)
        job = workflow.record_outline_ready(job_id=job.id, outline=outline)
        draft = DraftService(MockLLMClient(responses=[_draft_response()])).generate(
            job,
            task_spec,
            selected,
            research.evidence_map,
            outline=outline,
        )
        draft_store.save(draft)
        workflow.record_draft_ready(job_id=job.id, draft=draft)
        existing_validation = ValidationService(MockLLMClient(responses=[_validation_response()])).validate(
            draft.content,
            draft_id=draft.id,
            task_spec=task_spec,
            evidence_map=research.evidence_map.notes,
        )
        validation_store.save(job.id, existing_validation, version=1)

        draft_client = MockLLMClient(responses=[])
        validation_client = MockLLMClient(responses=[_validation_response()])
        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(MockLLMClient(responses=[])),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(draft_client),
            draft_store=draft_store,
            validation_service=ValidationService(validation_client),
            validation_store=validation_store,
            task_store=task_store,
            topic_store=topic_store,
            source_store=source_store,
        )

        result = runner.run_selected_job(job.id)
        validation_v2 = validation_store.load(job.id, 2)

    assert draft_client.calls == []
    assert validation_client.calls
    assert result.draft.id == draft.id
    assert result.validation.draft_id == draft.id
    assert validation_v2.draft_id == draft.id
    assert result.job.validation_report_id == f"{draft.id}:v002"


def test_revision_loop_writes_draft_v2_reruns_validation_and_exports() -> None:
    with LocalTempDir() as tmp_path:
        job_store = EssayJobStore(tmp_path / "essay_store")
        topic_store = TopicRoundStore(tmp_path / "topic_store")
        workflow = EssayWorkflow(job_store, topic_store)
        source_store = SourceStore(tmp_path / "source_store")
        task_store = TaskSpecStore(tmp_path / "task_store")
        research_plan_store = ResearchPlanStore(tmp_path / "research_plan_store")
        research_store = ResearchStore(tmp_path / "research_store")
        outline_store = ThesisOutlineStore(tmp_path / "outline_store")
        draft_store = DraftStore(tmp_path / "draft_store")
        validation_store = ValidationStore(tmp_path / "validation_store")
        export_store = FinalExportStore(tmp_path / "export_store")

        task_spec = _task_spec()
        task_store.save(task_spec)
        job = workflow.create_job(job_id="job1", task_spec_id=task_spec.id, source_ids=["src1"])
        round_ = workflow.record_topic_round(
            job_id=job.id,
            topic_result=TopicIdeationResult(task_spec_id=task_spec.id, candidates=[_candidate()]),
        )
        selected = workflow.select_topic(job_id=job.id, round_number=round_.round_number, topic_id="topic_001")
        manifest = _save_source(source_store)
        revision_client = MockLLMClient(responses=[_revision_draft_response()])
        validation_client = MockLLMClient(responses=[_failed_validation_response(), _validation_response()])
        runner = MvpWorkflowRunner(
            workflow=workflow,
            retriever=TopicEvidenceRetriever(source_store),
            research_planning_service=ResearchPlanningService(),
            research_plan_store=research_plan_store,
            research_service=FinalTopicResearchService(MockLLMClient(responses=[_research_response()])),
            research_store=research_store,
            outline_service=_outline_service(),
            outline_store=outline_store,
            draft_service=DraftService(MockLLMClient(responses=[_draft_response()])),
            draft_store=draft_store,
            validation_service=ValidationService(validation_client),
            validation_store=validation_store,
            revision_service=DraftRevisionService(revision_client),
            export_service=FinalExportService(),
            export_store=export_store,
            task_store=task_store,
            topic_store=topic_store,
            source_store=source_store,
        )

        first_result = runner.run_after_topic_selection(
            job_id=job.id,
            task_spec=task_spec,
            selected_topic=selected,
            index_manifests=[manifest],
        )
        revised_result = runner.run_revision_for_job(job.id)
        draft_v1 = draft_store.load(job.id, 1)
        draft_v2 = draft_store.load(job.id, 2)
        validation_v2 = validation_store.load(job.id, 2)
        final_job = job_store.load(job.id)
        loaded_export = export_store.load_latest(job.id)

    assert first_result.validation.passes is False
    assert first_result.job.current_stage == "revision"
    assert revision_client.calls
    assert "unsupported_claims" in revision_client.calls[0]["user"]
    assert draft_v1.version == 1
    assert draft_v2.version == 2
    assert draft_v2.content.startswith("Revised urban heat")
    assert revised_result.validation.passes is True
    assert validation_v2.draft_id == draft_v2.id
    assert final_job.current_stage == "complete"
    assert final_job.draft_id == draft_v2.id
    assert final_job.validation_report_id == f"{draft_v2.id}:v002"
    assert final_job.final_export_id == "final_export_002"
    assert loaded_export.draft_id == draft_v2.id


def _task_spec() -> TaskSpecification:
    return TaskSpecification(
        id="task1",
        version=1,
        raw_text="Write an essay on urban heat and housing.",
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


def _candidate() -> CandidateTopic:
    return CandidateTopic(
        id="topic_001",
        title="Urban heat and housing",
        research_question="How does urban heat affect renters?",
        tentative_thesis_direction="Urban heat should be treated as housing policy.",
        rationale="The uploaded source has relevant evidence.",
        source_leads=[
            TopicSourceLead(
                source_id="src1",
                chunk_ids=["src1-chunk-0001"],
            )
        ],
    )


def _save_source(source_store: SourceStore):
    chunk = SourceChunk(
        id="src1-chunk-0001",
        source_id="src1",
        ordinal=1,
        page_start=2,
        page_end=2,
        text="Urban heat affects renters in older housing.",
        char_count=44,
    )
    manifest = build_index_manifest(
        source_id="src1",
        index_path=str(source_store.source_dir("src1") / "index.sqlite"),
        chunks=[chunk],
    )
    source_store.save_result(
        SourceIngestionResult(
            source=SourceDocument(
                id="src1",
                original_path="source.pdf",
                file_name="source.pdf",
                source_type="pdf",
                page_count=2,
                char_count=44,
                extraction_method="pypdf",
                text_quality="readable",
                full_text_available=True,
                indexed=True,
                index_path=manifest.index_path,
                index_manifest_path=str(source_store.source_dir("src1") / "index_manifest.json"),
            ),
            pages=[],
            chunks=[chunk],
            source_card=SourceCard(
                source_id="src1",
                title="Urban Heat",
                source_type="pdf",
                page_count=2,
                extraction_method="pypdf",
                brief_summary="Heat and renters.",
            ),
            indexed=True,
            full_text_available=True,
            index_manifest=manifest,
        )
    )
    return manifest


def _research_response() -> dict:
    return {
        "notes": [
            {
                "source_id": "src1",
                "chunk_id": "src1-chunk-0001",
                "page_start": 2,
                "page_end": 2,
                "claim": "Urban heat affects renters in older housing.",
                "quote": "Urban heat affects renters in older housing.",
                "paraphrase": "The source connects heat risk to older rental housing.",
                "relevance": "Directly supports the housing-policy topic.",
                "supports_topic": True,
                "evidence_type": "argument",
                "tags": ["urban heat", "housing"],
                "confidence": 0.9,
            }
        ],
        "evidence_groups": [
            {
                "label": "Housing risk",
                "purpose": "thesis_support",
                "note_ids": ["note_001"],
                "synthesis": "Heat risk can support a housing-policy argument.",
            }
        ],
        "gaps": [],
        "conflicts": [],
        "warnings": [],
    }


def _draft_response() -> dict:
    return {
        "content": "Urban heat affects renters in older housing, which makes heat policy a housing issue.",
        "section_source_map": [
            {
                "section_id": "s1",
                "heading": "Body",
                "note_ids": ["note_001"],
                "source_ids": ["src1"],
            }
        ],
        "bibliography_candidates": [],
        "known_weak_spots": [],
    }


def _validation_response() -> dict:
    return {
        "unsupported_claims": [],
        "citation_issues": [],
        "rubric_scores": [],
        "assignment_fit": {"passes": True, "explanation": "Fits the assignment."},
        "length_check": {"actual_words": 13, "target_words": None, "passes": True},
        "style_issues": [],
        "revision_suggestions": [],
        "overall_quality": 0.8,
    }


def _failed_validation_response() -> dict:
    return {
        "unsupported_claims": [{"claim": "Urban heat always causes eviction.", "paragraph": 1}],
        "citation_issues": [],
        "rubric_scores": [],
        "assignment_fit": {"passes": True, "explanation": "Mostly fits the assignment."},
        "length_check": {"actual_words": 13, "target_words": None, "passes": True},
        "style_issues": [],
        "revision_suggestions": ["Remove or qualify the unsupported eviction claim."],
        "overall_quality": 0.5,
    }


def _revision_draft_response() -> dict:
    return {
        "content": "Revised urban heat policy should be treated as housing policy because older rental housing can increase heat risk.",
        "section_source_map": [
            {
                "section_id": "s1",
                "heading": "Body",
                "note_ids": ["note_001"],
                "source_ids": ["src1"],
            }
        ],
        "bibliography_candidates": ["Urban Heat. Uploaded source PDF."],
        "known_weak_spots": [],
    }


def _outline_service() -> ThesisOutlineService:
    return ThesisOutlineService(MockLLMClient(responses=[_outline_response()]))


def _outline_response() -> dict:
    return {
        "working_thesis": "Urban heat should be treated as housing policy.",
        "sections": [
            {
                "heading": "Introduction",
                "purpose": "introduce topic and thesis",
                "key_points": ["Urban heat should be treated as housing policy."],
                "note_ids": [],
                "target_words": None,
            },
            {
                "heading": "Housing risk",
                "purpose": "thesis_support",
                "key_points": ["Heat risk can support a housing-policy argument."],
                "note_ids": ["note_001"],
                "target_words": None,
            },
            {
                "heading": "Conclusion",
                "purpose": "synthesize argument",
                "key_points": ["Return to the housing-policy stakes."],
                "note_ids": [],
                "target_words": None,
            },
        ],
    }
