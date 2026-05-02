from __future__ import annotations

from dataclasses import replace

from essay_writer.drafting.schema import EssayDraft
from essay_writer.drafting.storage import DraftStore
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.jobs.storage import EssayJobStore
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.manual_revision.service import ManualRevisionService
from essay_writer.manual_revision.storage import ManualRevisionRequestStore, ManualRevisionRunStore
from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.outlining.storage import ThesisOutlineStore
from essay_writer.research.schema import EvidenceMap, FinalTopicResearchResult, ResearchNote, ResearchReport
from essay_writer.research.storage import ResearchStore
from essay_writer.research_planning.schema import ResearchPlan
from essay_writer.research_planning.storage import ResearchPlanStore
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.schema import SelectedTopic
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.tone_alignment.schema import ToneAlignmentReport
from essay_writer.validation.checks import run_deterministic_checks
from essay_writer.validation.schema import (
    AssignmentFit,
    LengthCheck,
    LLMJudgmentResult,
    ValidationReport,
)
from tests.task_spec._tmp import LocalTempDir


class FakeValidationService:
    def validate(
        self,
        draft_text: str,
        *,
        draft_id: str,
        task_spec: TaskSpecification,
        evidence_map,
        bibliography_candidates=None,
        source_cards=None,
        model=None,
    ) -> ValidationReport:
        del task_spec, evidence_map, bibliography_candidates, source_cards, model
        det = run_deterministic_checks(draft_text)
        return ValidationReport(
            draft_id=draft_id,
            task_spec_id="task1",
            deterministic=det,
            llm_judgment=LLMJudgmentResult(
                unsupported_claims=[],
                citation_issues=[],
                rubric_scores=[],
                assignment_fit=AssignmentFit(passes=True, explanation="Fits."),
                length_check=LengthCheck(actual_words=det.word_count, target_words=None, passes=True),
                style_issues=[],
                diagnostics=[],
                revision_suggestions=[],
                overall_quality=0.9 if "Improved sentence." in draft_text else 0.6,
            ),
        )


class FakeToneAlignmentService:
    def evaluate(
        self,
        draft_text: str,
        *,
        draft_id: str,
        task_spec: TaskSpecification,
        writing_style_payload,
        model=None,
    ) -> ToneAlignmentReport:
        del task_spec, writing_style_payload, model
        return ToneAlignmentReport(
            draft_id=draft_id,
            writing_style_content_id="style_001",
            overall_alignment=0.85 if "Improved sentence." in draft_text else 0.5,
            requires_revision="Improved sentence." not in draft_text,
            revision_targets=["Tighten the rhythm."],
        )


class FakeRevisionService:
    def revise(
        self,
        job,
        task_spec,
        selected_topic,
        evidence_map,
        *,
        outline,
        previous_draft: EssayDraft,
        validation,
        version: int,
        source_packets=None,
        writing_style_payload=None,
        tone_alignment=None,
        user_instruction=None,
        change_summary=None,
        selected_lenses=None,
        model=None,
    ) -> EssayDraft:
        del job, task_spec, selected_topic, evidence_map, outline, validation, source_packets
        del writing_style_payload, tone_alignment, user_instruction, change_summary, selected_lenses, model
        return replace(
            previous_draft,
            id="draft_revised",
            version=version,
            content=previous_draft.content + "\n\nImproved sentence.",
        )


def test_save_user_edit_creates_new_draft_with_parent_provenance() -> None:
    with LocalTempDir() as tmp_path:
        service, job_id, initial_draft = _build_service(tmp_path)

        saved = service.save_user_edit(
            job_id=job_id,
            content="User edit paragraph.\n\nSecond paragraph.",
            base_draft_id=initial_draft.id,
        )

    assert saved.origin == "user_edit"
    assert saved.created_by == "user"
    assert saved.parent_draft_id == initial_draft.id
    assert saved.version == 2


def test_create_run_review_only_stores_anti_ai_and_tone_warning_without_samples() -> None:
    with LocalTempDir() as tmp_path:
        service, job_id, initial_draft = _build_service(tmp_path)

        request, run, result_draft = service.create_run(
            job_id=job_id,
            source_draft_id=initial_draft.id,
            mode="review_only",
            instruction="Check the tone.",
            selected_lenses=["tone", "anti_ai"],
        )

    assert request.mode == "review_only"
    assert run.pre_revision_anti_ai is not None
    assert run.pre_revision_tone_alignment is None
    assert result_draft is None
    assert any("no writing-style samples" in warning for warning in run.warnings)


def test_create_run_revise_saves_result_draft_and_post_validation() -> None:
    with LocalTempDir() as tmp_path:
        service, job_id, initial_draft = _build_service(tmp_path)

        request, run, result_draft = service.create_run(
            job_id=job_id,
            source_draft_id=initial_draft.id,
            mode="revise",
            instruction="Tighten the prose.",
            selected_lenses=["evidence", "anti_ai"],
        )
        latest = DraftStore(tmp_path / "drafts").load_latest(job_id)

    assert request.mode == "revise"
    assert result_draft is not None
    assert result_draft.origin == "manual_llm_revision"
    assert result_draft.parent_draft_id == initial_draft.id
    assert result_draft.manual_request_id == request.id
    assert "Improved sentence." in result_draft.content
    assert run.result_draft_id == result_draft.id
    assert run.post_revision_validation is not None
    assert latest.id == result_draft.id


def _build_service(tmp_path):
    job_store = EssayJobStore(tmp_path / "jobs_store")
    topic_store = TopicRoundStore(tmp_path / "topics_store")
    workflow = EssayWorkflow(job_store, topic_store)
    task_store = TaskSpecStore(tmp_path / "task_specs")
    research_plan_store = ResearchPlanStore(tmp_path / "research_plans")
    research_store = ResearchStore(tmp_path / "research")
    outline_store = ThesisOutlineStore(tmp_path / "outlines")
    draft_store = DraftStore(tmp_path / "drafts")

    task = TaskSpecification(
        id="task1",
        version=1,
        raw_text="Write an essay.",
        source_document_ids=["src1"],
        citation_style="MLA",
    )
    task_store.save(task)

    job = workflow.create_job(task_spec_id=task.id, source_ids=["src1"])
    job = job_store.save(replace(job, selected_topic_id="topic1", selected_topic_round_id="round1"))
    topic_store.save_selected_topic(
        SelectedTopic(
            job_id=job.id,
            round_id="round1",
            topic_id="topic1",
            title="Topic",
            research_question="RQ",
            tentative_thesis_direction="TD",
        )
    )

    research_plan_store.save(
        ResearchPlan(
            id="research_plan_v001",
            job_id=job.id,
            selected_topic_id="topic1",
            version=1,
            research_question="RQ",
            source_requirements=[],
            uploaded_source_priorities=[],
            expected_evidence_categories=[],
        )
    )
    research_store.save_result(_research(job.id), version=1)
    outline_store.save(
        ThesisOutline(
            id="outline_v001",
            job_id=job.id,
            selected_topic_id="topic1",
            research_plan_id="research_plan_v001",
            evidence_map_id="evidence_map_v001",
            version=1,
            working_thesis="Working thesis",
            sections=[OutlineSection(id="s1", heading="Body", purpose="Develop the argument.")],
        )
    )
    initial_draft = EssayDraft(
        id="draft_initial",
        job_id=job.id,
        version=1,
        selected_topic_id="topic1",
        content="Original paragraph.\n\nSecond paragraph.",
        outline_id="outline_v001",
        citation_style="MLA",
    )
    draft_store.save(initial_draft)

    service = ManualRevisionService(
        workflow=workflow,
        task_store=task_store,
        topic_store=topic_store,
        research_plan_store=research_plan_store,
        research_store=research_store,
        outline_store=outline_store,
        draft_store=draft_store,
        export_store=FinalExportStore(tmp_path / "exports"),
        request_store=ManualRevisionRequestStore(tmp_path / "manual_requests"),
        run_store=ManualRevisionRunStore(tmp_path / "manual_runs"),
        validation_service=FakeValidationService(),
        tone_alignment_service=FakeToneAlignmentService(),
        revision_service=FakeRevisionService(),
        source_store=None,
        source_access_service=None,
        writing_style_sample_store=None,
        writing_style_content_store=None,
    )
    return service, job.id, initial_draft


def _research(job_id: str) -> FinalTopicResearchResult:
    note = ResearchNote(
        id="note1",
        source_id="src1",
        chunk_id="chunk1",
        page_start=1,
        page_end=1,
        claim="A grounded claim.",
        quote=None,
        paraphrase="A grounded claim.",
        relevance="High",
        supports_topic=True,
        evidence_type="argument",
        confidence=0.9,
    )
    evidence_map = EvidenceMap(
        id="evidence_map_v001",
        job_id=job_id,
        selected_topic_id="topic1",
        research_question="RQ",
        thesis_direction="TD",
        notes=[note],
        source_ids=["src1"],
    )
    report = ResearchReport(
        job_id=job_id,
        selected_topic_id="topic1",
        evidence_map_id=evidence_map.id,
        note_count=1,
        source_count=1,
    )
    return FinalTopicResearchResult(evidence_map=evidence_map, report=report)
