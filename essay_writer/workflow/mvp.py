from __future__ import annotations

from dataclasses import dataclass

from essay_writer.drafting.schema import EssayDraft
from essay_writer.drafting.revision import DraftRevisionService
from essay_writer.drafting.service import DraftService
from essay_writer.drafting.storage import DraftStore
from essay_writer.exporting.schema import FinalEssayExport
from essay_writer.exporting.service import FinalExportService
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.jobs.schema import EssayJob
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.outlining.schema import ThesisOutline
from essay_writer.outlining.service import ThesisOutlineService
from essay_writer.outlining.storage import ThesisOutlineStore
from essay_writer.research.schema import FinalTopicResearchResult
from essay_writer.research.service import FinalTopicResearchService
from essay_writer.research.storage import ResearchStore
from essay_writer.research_planning.schema import ResearchPlan
from essay_writer.research_planning.service import ResearchPlanningService
from essay_writer.research_planning.storage import ResearchPlanStore
from essay_writer.sources.schema import SourceCard, SourceIndexManifest
from essay_writer.sources.storage import SourceStore
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.retrieval import TopicEvidenceRetriever
from essay_writer.topic_ideation.schema import RetrievedTopicEvidence, SelectedTopic
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.validation.schema import ValidationReport
from essay_writer.validation.service import ValidationService
from essay_writer.validation.storage import ValidationStore


class WorkflowContractError(RuntimeError):
    """Raised when persisted workflow artifacts do not match the job state."""


class InsufficientEvidenceError(RuntimeError):
    """Raised when a selected topic has too little evidence to draft safely."""


class WorkflowNotRunnableError(RuntimeError):
    """Raised when a job is already blocked or failed and should not be resumed."""


@dataclass(frozen=True)
class MvpWorkflowResult:
    job: EssayJob
    retrieved_evidence: RetrievedTopicEvidence
    research_plan: ResearchPlan
    research: FinalTopicResearchResult
    outline: ThesisOutline
    draft: EssayDraft
    validation: ValidationReport
    final_export: FinalEssayExport | None = None


class MvpWorkflowRunner:
    """Run the uploaded-source-only MVP after topic selection."""

    def __init__(
        self,
        *,
        workflow: EssayWorkflow,
        retriever: TopicEvidenceRetriever,
        research_planning_service: ResearchPlanningService,
        research_plan_store: ResearchPlanStore,
        research_service: FinalTopicResearchService,
        research_store: ResearchStore,
        outline_service: ThesisOutlineService,
        outline_store: ThesisOutlineStore,
        draft_service: DraftService,
        draft_store: DraftStore,
        validation_service: ValidationService,
        validation_store: ValidationStore,
        revision_service: DraftRevisionService | None = None,
        export_service: FinalExportService | None = None,
        export_store: FinalExportStore | None = None,
        task_store: TaskSpecStore | None = None,
        topic_store: TopicRoundStore | None = None,
        source_store: SourceStore | None = None,
    ) -> None:
        self._workflow = workflow
        self._retriever = retriever
        self._research_planning_service = research_planning_service
        self._research_plan_store = research_plan_store
        self._research_service = research_service
        self._research_store = research_store
        self._outline_service = outline_service
        self._outline_store = outline_store
        self._draft_service = draft_service
        self._draft_store = draft_store
        self._revision_service = revision_service
        self._validation_service = validation_service
        self._validation_store = validation_store
        self._export_service = export_service
        self._export_store = export_store
        self._task_store = task_store
        self._topic_store = topic_store
        self._source_store = source_store

    def run_after_topic_selection(
        self,
        *,
        job_id: str,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        index_manifests: list[SourceIndexManifest],
        model: str | None = None,
    ) -> MvpWorkflowResult:
        try:
            job = self._workflow.ensure_research_planning_ready(job_id)
            _validate_contract(job, task_spec, selected_topic, index_manifests)
            retrieved = self._retriever.retrieve_for_selected_topic(
                selected_topic,
                index_manifests=index_manifests,
            )
            return self._run_research_to_validation(
                job=job,
                task_spec=task_spec,
                selected_topic=selected_topic,
                index_manifests=index_manifests,
                retrieved=retrieved,
                model=model,
            )
        except InsufficientEvidenceError:
            raise
        except Exception as exc:
            self._mark_error_if_possible(job_id, stage="workflow", message=str(exc))
            raise

    def run_selected_job(self, job_id: str, *, model: str | None = None) -> MvpWorkflowResult:
        """Resume or complete a selected uploaded-source MVP job from persisted artifacts."""
        try:
            task_store, topic_store, source_store = self._require_persisted_stores()
            job = self._workflow.load_job(job_id)
            if job.status in {"blocked", "error"}:
                message = job.error_state.message if job.error_state else f"Job is {job.status}."
                raise WorkflowNotRunnableError(message)
            if job.task_spec_id is None:
                raise WorkflowContractError("Job has no task_spec_id.")

            task_spec = task_store.load_latest(job.task_spec_id)
            selected_topic = topic_store.load_selected_topic(job_id)
            index_manifests = _load_index_manifests(source_store, job.source_ids)
            _validate_contract(job, task_spec, selected_topic, index_manifests)
            retrieved = self._retriever.retrieve_for_selected_topic(
                selected_topic,
                index_manifests=index_manifests,
            )

            if job.status == "research_planning_ready":
                return self._run_research_to_validation(
                    job=job,
                    task_spec=task_spec,
                    selected_topic=selected_topic,
                    index_manifests=index_manifests,
                    retrieved=retrieved,
                    model=model,
                )
            if job.status == "drafting_ready":
                research_plan = self._research_plan_store.load_latest(job_id)
                research = self._research_store.load_latest(job_id)
                _validate_research_plan(job, selected_topic, research_plan)
                _validate_research(job, selected_topic, research)
                return self._run_draft_to_validation(
                    job=job,
                    task_spec=task_spec,
                    selected_topic=selected_topic,
                    retrieved=retrieved,
                    research_plan=research_plan,
                    research=research,
                    model=model,
                )
            if job.status == "validation_ready":
                research_plan = self._research_plan_store.load_latest(job_id)
                research = self._research_store.load_latest(job_id)
                outline = self._outline_store.load_latest(job_id)
                draft = self._draft_store.load_latest(job_id)
                _validate_research_plan(job, selected_topic, research_plan)
                _validate_research(job, selected_topic, research)
                _validate_outline(job, selected_topic, research_plan, research, outline)
                _validate_draft(job, selected_topic, draft)
                return self._run_validation_only(
                    task_spec=task_spec,
                    retrieved=retrieved,
                    research_plan=research_plan,
                    research=research,
                    outline=outline,
                    draft=draft,
                    model=model,
                )
            if job.status == "validation_complete" and job.current_stage == "revision":
                return self.run_revision_for_job(job_id, model=model)
            if job.status == "validation_complete":
                research_plan = self._research_plan_store.load_latest(job_id)
                research = self._research_store.load_latest(job_id)
                outline = self._outline_store.load_latest(job_id)
                draft = self._draft_store.load_latest(job_id)
                validation = self._validation_store.load_latest(job_id)
                final_export = _load_final_export(self._export_store, job) if self._export_store is not None else None
                _validate_research_plan(job, selected_topic, research_plan)
                _validate_research(job, selected_topic, research)
                _validate_outline(job, selected_topic, research_plan, research, outline)
                _validate_draft(job, selected_topic, draft)
                if validation.draft_id != draft.id:
                    raise WorkflowContractError("Latest validation report does not match latest draft.")
                return MvpWorkflowResult(
                    job=job,
                    retrieved_evidence=retrieved,
                    research_plan=research_plan,
                    research=research,
                    outline=outline,
                    draft=draft,
                    validation=validation,
                    final_export=final_export,
                )
            raise WorkflowContractError(f"Job is not ready to resume the MVP workflow: {job.status}")
        except (InsufficientEvidenceError, WorkflowNotRunnableError):
            raise
        except Exception as exc:
            self._mark_error_if_possible(job_id, stage="workflow", message=str(exc))
            raise

    def run_revision_for_job(self, job_id: str, *, model: str | None = None) -> MvpWorkflowResult:
        """Create the next draft version from failed validation feedback and rerun validation."""
        if self._revision_service is None:
            raise ValueError("revision_service is required for revision jobs.")
        try:
            task_store, topic_store, source_store = self._require_persisted_stores()
            job = self._workflow.load_job(job_id)
            if job.status in {"blocked", "error"}:
                message = job.error_state.message if job.error_state else f"Job is {job.status}."
                raise WorkflowNotRunnableError(message)
            if job.status != "validation_complete" or job.current_stage != "revision":
                raise WorkflowContractError(f"Job is not ready for revision: {job.status}/{job.current_stage}")

            task_spec = task_store.load_latest(job.task_spec_id or "")
            selected_topic = topic_store.load_selected_topic(job_id)
            index_manifests = _load_index_manifests(source_store, job.source_ids)
            _validate_contract(job, task_spec, selected_topic, index_manifests)
            retrieved = self._retriever.retrieve_for_selected_topic(
                selected_topic,
                index_manifests=index_manifests,
            )
            research_plan = self._research_plan_store.load_latest(job_id)
            research = self._research_store.load_latest(job_id)
            outline = self._outline_store.load_latest(job_id)
            previous_draft = self._draft_store.load_latest(job_id)
            validation = self._validation_store.load_latest(job_id)
            _validate_research_plan(job, selected_topic, research_plan)
            _validate_research(job, selected_topic, research)
            _validate_outline(job, selected_topic, research_plan, research, outline)
            _validate_draft(job, selected_topic, previous_draft)
            if validation.draft_id != previous_draft.id:
                raise WorkflowContractError("Latest validation report does not match latest draft.")
            if validation.passes:
                raise WorkflowContractError("Revision requires a failed validation report.")

            revision_version = self._draft_store.next_version(job_id)
            revised_draft = self._revision_service.revise(
                job,
                task_spec,
                selected_topic,
                research.evidence_map,
                outline=outline,
                previous_draft=previous_draft,
                validation=validation,
                version=revision_version,
                model=model,
            )
            self._draft_store.save(revised_draft)
            self._workflow.record_draft_ready(job_id=job_id, draft=revised_draft)
            return self._run_validation_only(
                task_spec=task_spec,
                retrieved=retrieved,
                research_plan=research_plan,
                research=research,
                outline=outline,
                draft=revised_draft,
                model=model,
            )
        except (WorkflowNotRunnableError, WorkflowContractError):
            raise
        except Exception as exc:
            self._mark_error_if_possible(job_id, stage="revision", message=str(exc))
            raise

    def _run_research_to_validation(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        index_manifests: list[SourceIndexManifest],
        retrieved: RetrievedTopicEvidence,
        model: str | None,
    ) -> MvpWorkflowResult:
        try:
            research_plan_version = self._research_plan_store.next_version(job.id)
            research_plan = self._research_planning_service.create_plan(
                job=job,
                task_spec=task_spec,
                selected_topic=selected_topic,
                index_manifests=index_manifests,
                version=research_plan_version,
                external_search_allowed=False,
            )
            self._research_plan_store.save(research_plan)
            job = self._workflow.record_research_plan_complete(job_id=job.id, research_plan=research_plan)

            research_version = self._research_store.next_version(job.id)
            research = self._research_service.extract(
                job=job,
                task_spec=task_spec,
                selected_topic=selected_topic,
                retrieved_evidence=[retrieved],
                evidence_map_version=research_version,
                model=model,
            )
            self._research_store.save_result(research, version=research_version)
            if not research.evidence_map.notes:
                self._workflow.mark_blocked(
                    job_id=job.id,
                    stage="research",
                    message="Selected topic does not have enough retrieved evidence to draft safely.",
                )
                raise InsufficientEvidenceError("Selected topic does not have enough retrieved evidence to draft safely.")
            job = self._workflow.record_research_complete(job_id=job.id, research_result=research)
        except InsufficientEvidenceError:
            raise
        except Exception as exc:
            self._mark_error_if_possible(job.id, stage="research", message=str(exc))
            raise
        return self._run_draft_to_validation(
            job=job,
            task_spec=task_spec,
            selected_topic=selected_topic,
            retrieved=retrieved,
            research_plan=research_plan,
            research=research,
            model=model,
        )

    def _run_draft_to_validation(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        retrieved: RetrievedTopicEvidence,
        research_plan: ResearchPlan,
        research: FinalTopicResearchResult,
        model: str | None,
    ) -> MvpWorkflowResult:
        try:
            self._workflow.ensure_drafting_ready(job.id)
            outline_version = self._outline_store.next_version(job.id)
            outline = self._outline_service.create_outline(
                job=job,
                task_spec=task_spec,
                selected_topic=selected_topic,
                research_plan=research_plan,
                evidence_map=research.evidence_map,
                version=outline_version,
            )
            self._outline_store.save(outline)
            job = self._workflow.record_outline_ready(job_id=job.id, outline=outline)

            draft_version = self._draft_store.next_version(job.id)
            draft = self._draft_service.generate(
                job,
                task_spec,
                selected_topic,
                research.evidence_map,
                outline=outline,
                version=draft_version,
                model=model,
            )
            self._draft_store.save(draft)
            self._workflow.record_draft_ready(job_id=job.id, draft=draft)
        except Exception as exc:
            self._mark_error_if_possible(job.id, stage="drafting", message=str(exc))
            raise
        return self._run_validation_only(
            task_spec=task_spec,
            retrieved=retrieved,
            research_plan=research_plan,
            research=research,
            outline=outline,
            draft=draft,
            model=model,
        )

    def _run_validation_only(
        self,
        *,
        task_spec: TaskSpecification,
        retrieved: RetrievedTopicEvidence,
        research_plan: ResearchPlan,
        research: FinalTopicResearchResult,
        outline: ThesisOutline,
        draft: EssayDraft,
        model: str | None,
    ) -> MvpWorkflowResult:
        try:
            self._workflow.ensure_validation_ready(draft.job_id)
            job_for_validation = self._workflow.load_job(draft.job_id)
            source_cards = (
                _load_source_cards(self._source_store, job_for_validation.source_ids)
                if self._source_store is not None
                else []
            )
            validation_version = self._validation_store.next_version(draft.job_id)
            validation = self._validation_service.validate(
                draft.content,
                draft_id=draft.id,
                task_spec=task_spec,
                evidence_map=research.evidence_map.notes,
                bibliography_candidates=draft.bibliography_candidates,
                source_cards=source_cards,
                model=model,
            )
            self._validation_store.save(draft.job_id, validation, version=validation_version)
            job = self._workflow.record_validation_complete(
                job_id=draft.job_id,
                validation_report_id=f"{validation.draft_id}:v{validation_version:03d}",
                passes=validation.passes,
            )
            final_export = None
            if validation.passes and self._export_service is not None and self._export_store is not None:
                final_export = self._export_service.create_markdown_export(
                    job=job,
                    task_spec=task_spec,
                    draft=draft,
                    validation=validation,
                )
                self._export_store.save(final_export)
                job = self._workflow.record_final_export_ready(job_id=draft.job_id, export=final_export)
        except Exception as exc:
            self._mark_error_if_possible(draft.job_id, stage="validation", message=str(exc))
            raise

        return MvpWorkflowResult(
            job=job,
            retrieved_evidence=retrieved,
            research_plan=research_plan,
            research=research,
            outline=outline,
            draft=draft,
            validation=validation,
            final_export=final_export,
        )

    def _require_persisted_stores(self) -> tuple[TaskSpecStore, TopicRoundStore, SourceStore]:
        if self._task_store is None or self._topic_store is None or self._source_store is None:
            raise ValueError("task_store, topic_store, and source_store are required for run_selected_job().")
        return self._task_store, self._topic_store, self._source_store

    def _mark_error_if_possible(self, job_id: str, *, stage: str, message: str) -> None:
        try:
            job = self._workflow.load_job(job_id)
            if job.status in {"blocked", "error"}:
                return
            self._workflow.mark_error(job_id=job_id, stage=stage, message=message)
        except Exception:
            return


def _load_index_manifests(source_store: SourceStore, source_ids: list[str]) -> list[SourceIndexManifest]:
    manifests: list[SourceIndexManifest] = []
    for source_id in source_ids:
        try:
            manifests.append(source_store.load_index_manifest(source_id))
        except (FileNotFoundError, KeyError):
            continue
    return manifests


def _load_source_cards(source_store: SourceStore, source_ids: list[str]) -> list[SourceCard]:
    cards: list[SourceCard] = []
    for source_id in source_ids:
        try:
            cards.append(source_store.load_source_card(source_id))
        except (FileNotFoundError, KeyError):
            continue
    return cards


def _load_final_export(export_store: FinalExportStore | None, job: EssayJob) -> FinalEssayExport | None:
    if export_store is None or job.final_export_id is None:
        return None
    return export_store.load(job.id, job.final_export_id)


def _validate_contract(
    job: EssayJob,
    task_spec: TaskSpecification,
    selected_topic: SelectedTopic,
    index_manifests: list[SourceIndexManifest],
) -> None:
    if job.task_spec_id != task_spec.id:
        raise WorkflowContractError(
            f"Task spec id mismatch: job has {job.task_spec_id}, got {task_spec.id}."
        )
    if selected_topic.job_id != job.id:
        raise WorkflowContractError(
            f"Selected topic job_id mismatch: job has {job.id}, got {selected_topic.job_id}."
        )
    if job.selected_topic_id != selected_topic.topic_id:
        raise WorkflowContractError(
            f"Selected topic id mismatch: job has {job.selected_topic_id}, got {selected_topic.topic_id}."
        )
    if job.selected_topic_round_id != selected_topic.round_id:
        raise WorkflowContractError(
            f"Selected topic round mismatch: job has {job.selected_topic_round_id}, got {selected_topic.round_id}."
        )

    job_source_ids = set(job.source_ids)
    task_source_ids = set(task_spec.source_document_ids)
    if task_source_ids and not task_source_ids.issubset(job_source_ids):
        missing = sorted(task_source_ids - job_source_ids)
        raise WorkflowContractError(f"Task spec references sources not attached to job: {', '.join(missing)}.")

    manifest_source_ids = {manifest.source_id for manifest in index_manifests}
    if not manifest_source_ids.issubset(job_source_ids):
        extra = sorted(manifest_source_ids - job_source_ids)
        raise WorkflowContractError(f"Index manifests do not belong to job sources: {', '.join(extra)}.")

    lead_source_ids = {lead.source_id for lead in selected_topic.source_leads}
    if not lead_source_ids.issubset(job_source_ids):
        missing = sorted(lead_source_ids - job_source_ids)
        raise WorkflowContractError(f"Selected topic references sources not attached to job: {', '.join(missing)}.")

    indexed_lead_sources = {
        lead.source_id
        for lead in selected_topic.source_leads
        if lead.chunk_ids or lead.suggested_source_search_queries
    }
    if not indexed_lead_sources.issubset(manifest_source_ids):
        missing = sorted(indexed_lead_sources - manifest_source_ids)
        raise WorkflowContractError(f"Selected topic references sources without index manifests: {', '.join(missing)}.")


def _validate_research(
    job: EssayJob,
    selected_topic: SelectedTopic,
    research: FinalTopicResearchResult,
) -> None:
    if research.evidence_map.job_id != job.id:
        raise WorkflowContractError("Research artifact does not belong to this job.")
    if research.evidence_map.selected_topic_id != selected_topic.topic_id:
        raise WorkflowContractError("Research artifact does not match selected topic.")
    if job.evidence_map_id and research.evidence_map.id != job.evidence_map_id:
        raise WorkflowContractError("Research artifact does not match job evidence_map_id.")


def _validate_research_plan(
    job: EssayJob,
    selected_topic: SelectedTopic,
    research_plan: ResearchPlan,
) -> None:
    if research_plan.job_id != job.id:
        raise WorkflowContractError("Research plan does not belong to this job.")
    if research_plan.selected_topic_id != selected_topic.topic_id:
        raise WorkflowContractError("Research plan does not match selected topic.")
    if job.research_plan_id and research_plan.id != job.research_plan_id:
        raise WorkflowContractError("Research plan does not match job research_plan_id.")


def _validate_outline(
    job: EssayJob,
    selected_topic: SelectedTopic,
    research_plan: ResearchPlan,
    research: FinalTopicResearchResult,
    outline: ThesisOutline,
) -> None:
    if outline.job_id != job.id:
        raise WorkflowContractError("Outline artifact does not belong to this job.")
    if outline.selected_topic_id != selected_topic.topic_id:
        raise WorkflowContractError("Outline artifact does not match selected topic.")
    if outline.research_plan_id != research_plan.id:
        raise WorkflowContractError("Outline artifact does not match research plan.")
    if outline.evidence_map_id != research.evidence_map.id:
        raise WorkflowContractError("Outline artifact does not match evidence map.")
    if job.outline_id and outline.id != job.outline_id:
        raise WorkflowContractError("Outline artifact does not match job outline_id.")


def _validate_draft(job: EssayJob, selected_topic: SelectedTopic, draft: EssayDraft) -> None:
    if draft.job_id != job.id:
        raise WorkflowContractError("Draft artifact does not belong to this job.")
    if draft.selected_topic_id != selected_topic.topic_id:
        raise WorkflowContractError("Draft artifact does not match selected topic.")
    if job.outline_id and draft.outline_id != job.outline_id:
        raise WorkflowContractError("Draft artifact does not match job outline_id.")
    if job.draft_id and draft.id != job.draft_id:
        raise WorkflowContractError("Draft artifact does not match job draft_id.")
