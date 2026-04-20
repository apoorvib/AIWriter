from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from essay_writer.jobs.schema import EssayJob, EssayJobErrorState
from essay_writer.jobs.storage import EssayJobStore
from essay_writer.drafting.schema import EssayDraft
from essay_writer.exporting.schema import FinalEssayExport
from essay_writer.outlining.schema import ThesisOutline
from essay_writer.research.schema import FinalTopicResearchResult
from essay_writer.research_planning.schema import ResearchPlan
from essay_writer.topic_ideation.schema import (
    CandidateTopic,
    RejectedTopic,
    SelectedTopic,
    TopicIdeationResult,
    TopicIdeationRound,
)
from essay_writer.topic_ideation.storage import TopicRoundStore


class TopicSelectionError(RuntimeError):
    """Raised when a topic selection or stage transition is invalid."""


class EssayWorkflow:
    def __init__(self, job_store: EssayJobStore, topic_store: TopicRoundStore) -> None:
        self._job_store = job_store
        self._topic_store = topic_store

    def create_job(
        self,
        *,
        job_id: str | None = None,
        task_spec_id: str | None = None,
        source_ids: list[str] | None = None,
    ) -> EssayJob:
        status = "created"
        current_stage = "created"
        if task_spec_id and source_ids:
            status = "sources_ready"
            current_stage = "topic_ideation"
        elif task_spec_id:
            status = "task_spec_ready"
            current_stage = "source_ingestion"
        job = EssayJob(
            id=job_id or f"job-{uuid4().hex[:16]}",
            status=status,  # type: ignore[arg-type]
            current_stage=current_stage,
            task_spec_id=task_spec_id,
            source_ids=list(source_ids or []),
        )
        return self._job_store.create(job)

    def load_job(self, job_id: str) -> EssayJob:
        return self._job_store.load(job_id)

    def attach_task_spec(self, *, job_id: str, task_spec_id: str) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.task_spec_id is not None and job.task_spec_id != task_spec_id:
            raise TopicSelectionError(
                f"Job already has task_spec_id={job.task_spec_id}; cannot attach task_spec_id={task_spec_id}."
            )
        status = "task_spec_ready"
        current_stage = "source_ingestion"
        if job.source_ids:
            status = "sources_ready"
            current_stage = "topic_ideation"
        updated = replace(
            job,
            status=status,
            current_stage=current_stage,
            task_spec_id=task_spec_id,
            error_state=None,
        )
        return self._job_store.save(updated)

    def attach_sources(self, *, job_id: str, source_ids: list[str]) -> EssayJob:
        job = self._job_store.load(job_id)
        merged_source_ids = [*job.source_ids]
        for source_id in source_ids:
            if source_id not in merged_source_ids:
                merged_source_ids.append(source_id)
        status = "sources_ready" if job.task_spec_id is not None else "created"
        current_stage = "topic_ideation" if job.task_spec_id is not None else "source_ingestion"
        updated = replace(
            job,
            status=status,
            current_stage=current_stage,
            source_ids=merged_source_ids,
            error_state=None,
        )
        return self._job_store.save(updated)

    def mark_blocked(self, *, job_id: str, stage: str, message: str) -> EssayJob:
        job = self._job_store.load(job_id)
        updated = replace(
            job,
            status="blocked",
            current_stage=stage,
            error_state=EssayJobErrorState(stage=stage, message=message),
        )
        return self._job_store.save(updated)

    def mark_error(self, *, job_id: str, stage: str, message: str) -> EssayJob:
        job = self._job_store.load(job_id)
        updated = replace(
            job,
            status="error",
            current_stage=stage,
            error_state=EssayJobErrorState(stage=stage, message=message),
        )
        return self._job_store.save(updated)

    def record_topic_round(
        self,
        *,
        job_id: str,
        topic_result: TopicIdeationResult,
        user_instruction: str | None = None,
        previous_candidates: list[CandidateTopic] | None = None,
    ) -> TopicIdeationRound:
        job = self._job_store.load(job_id)
        if job.task_spec_id is None:
            raise TopicSelectionError("Cannot record topic round before task_spec_id is set.")
        if job.task_spec_id != topic_result.task_spec_id:
            raise TopicSelectionError(
                f"Topic result task_spec_id={topic_result.task_spec_id} does not match job task_spec_id={job.task_spec_id}."
            )

        existing_rounds = self._topic_store.list_rounds(job_id)
        round_number = len(existing_rounds) + 1
        round_id = f"{job_id}-topic-round-{round_number:03d}"
        previous_topic_ids = [candidate.id for candidate in (previous_candidates or [])]
        round_ = TopicIdeationRound(
            id=round_id,
            job_id=job_id,
            task_spec_id=topic_result.task_spec_id,
            round_number=round_number,
            user_instruction=user_instruction,
            previous_topic_ids=previous_topic_ids,
            candidates=topic_result.candidates,
            prompt_version=topic_result.prompt_version,
        )
        self._topic_store.save_round(round_)
        updated = replace(
            job,
            status="topic_selection_ready",
            current_stage="topic_selection",
            topic_round_ids=[*job.topic_round_ids, round_id],
        )
        self._job_store.save(updated)
        return round_

    def get_previous_candidates(self, job_id: str) -> list[CandidateTopic]:
        candidates: list[CandidateTopic] = []
        for round_ in self._topic_store.list_rounds(job_id):
            candidates.extend(round_.candidates)
        return candidates

    def get_rejected_topics(self, job_id: str) -> list[RejectedTopic]:
        return self._topic_store.list_rejected_topics(job_id)

    def reject_topic(
        self,
        *,
        job_id: str,
        round_number: int,
        topic_id: str,
        reason: str,
    ) -> RejectedTopic:
        round_ = self._topic_store.load_round(job_id, round_number)
        topic = next((candidate for candidate in round_.candidates if candidate.id == topic_id), None)
        if topic is None:
            raise TopicSelectionError(f"Topic id not found in round {round_number}: {topic_id}")
        rejected = RejectedTopic(
            job_id=job_id,
            round_id=round_.id,
            topic_id=topic.id,
            title=topic.title,
            reason=reason,
        )
        self._topic_store.save_rejected_topic(rejected)
        return rejected

    def select_topic(self, *, job_id: str, round_number: int, topic_id: str) -> SelectedTopic:
        job = self._job_store.load(job_id)
        round_ = self._topic_store.load_round(job_id, round_number)
        topic = next((candidate for candidate in round_.candidates if candidate.id == topic_id), None)
        if topic is None:
            raise TopicSelectionError(f"Topic id not found in round {round_number}: {topic_id}")

        selected = SelectedTopic(
            job_id=job_id,
            round_id=round_.id,
            topic_id=topic.id,
            title=topic.title,
            research_question=topic.research_question,
            tentative_thesis_direction=topic.tentative_thesis_direction,
            source_leads=topic.source_leads,
        )
        self._topic_store.save_selected_topic(selected)
        updated = replace(
            job,
            status="research_planning_ready",
            current_stage="research_planning",
            selected_topic_id=topic.id,
            selected_topic_round_id=round_.id,
        )
        self._job_store.save(updated)
        return selected

    def record_research_plan_complete(self, *, job_id: str, research_plan: ResearchPlan) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.selected_topic_id != research_plan.selected_topic_id:
            raise TopicSelectionError("Research plan does not match the job's selected topic.")
        updated = replace(
            job,
            current_stage="research",
            research_plan_id=research_plan.id,
        )
        return self._job_store.save(updated)

    def ensure_research_planning_ready(self, job_id: str) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.selected_topic_id is None or job.selected_topic_round_id is None:
            raise TopicSelectionError("Research planning requires a selected topic.")
        if job.status != "research_planning_ready":
            raise TopicSelectionError(f"Job is not ready for research planning: {job.status}")
        return job

    def record_research_complete(self, *, job_id: str, research_result: FinalTopicResearchResult) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.selected_topic_id != research_result.evidence_map.selected_topic_id:
            raise TopicSelectionError("Research result does not match the job's selected topic.")
        updated = replace(
            job,
            status="drafting_ready",
            current_stage="drafting",
            evidence_map_id=research_result.evidence_map.id,
        )
        return self._job_store.save(updated)

    def record_outline_ready(self, *, job_id: str, outline: ThesisOutline) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.selected_topic_id != outline.selected_topic_id:
            raise TopicSelectionError("Outline does not match the job's selected topic.")
        if job.research_plan_id != outline.research_plan_id:
            raise TopicSelectionError("Outline does not match the job's research plan.")
        if job.evidence_map_id != outline.evidence_map_id:
            raise TopicSelectionError("Outline does not match the job's evidence map.")
        updated = replace(
            job,
            current_stage="drafting",
            outline_id=outline.id,
        )
        return self._job_store.save(updated)

    def ensure_drafting_ready(self, job_id: str) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.status != "drafting_ready" or job.evidence_map_id is None:
            raise TopicSelectionError(f"Job is not ready for drafting: {job.status}")
        return job

    def record_draft_ready(self, *, job_id: str, draft: EssayDraft) -> EssayJob:
        job = self._job_store.load(job_id)
        if draft.job_id != job.id:
            raise TopicSelectionError("Draft does not belong to this job.")
        if job.selected_topic_id != draft.selected_topic_id:
            raise TopicSelectionError("Draft does not match the job's selected topic.")
        updated = replace(
            job,
            status="validation_ready",
            current_stage="validation",
            draft_id=draft.id,
            validation_report_id=None,
            final_export_id=None,
        )
        return self._job_store.save(updated)

    def ensure_validation_ready(self, job_id: str) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.status != "validation_ready" or job.draft_id is None:
            raise TopicSelectionError(f"Job is not ready for validation: {job.status}")
        return job

    def record_validation_complete(
        self,
        *,
        job_id: str,
        validation_report_id: str,
        passes: bool,
    ) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.draft_id is None:
            raise TopicSelectionError("Validation requires a draft.")
        updated = replace(
            job,
            status="validation_complete",
            current_stage="complete" if passes else "revision",
            validation_report_id=validation_report_id,
        )
        return self._job_store.save(updated)

    def record_final_export_ready(self, *, job_id: str, export: FinalEssayExport) -> EssayJob:
        job = self._job_store.load(job_id)
        if job.draft_id != export.draft_id:
            raise TopicSelectionError("Final export does not match the job's draft.")
        if job.validation_report_id != export.validation_report_id:
            raise TopicSelectionError("Final export does not match the job's validation report.")
        updated = replace(
            job,
            current_stage="complete",
            final_export_id=export.id,
        )
        return self._job_store.save(updated)
