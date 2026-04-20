from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pdf_pipeline.document_reader import DocumentReader
from pdf_pipeline.models import DocumentExtractionResult
from essay_writer.jobs.schema import EssayJob
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.sources.ingestion import SourceIngestionService
from essay_writer.sources.schema import SourceIngestionResult, SourceIndexManifest
from essay_writer.task_spec.parser import TaskSpecParser
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.schema import TopicIdeationRound
from essay_writer.topic_ideation.service import TopicIdeationService


class WorkflowBlockedError(RuntimeError):
    """Raised when a workflow stage cannot proceed until the user resolves a block."""


class AssignmentExtractor(Protocol):
    def extract(self, document_path: str | Path) -> DocumentExtractionResult: ...


@dataclass(frozen=True)
class MvpBootstrapResult:
    job: EssayJob
    task_spec: TaskSpecification
    source_results: list[SourceIngestionResult]

    @property
    def index_manifests(self) -> list[SourceIndexManifest]:
        return [result.index_manifest for result in self.source_results if result.index_manifest is not None]


@dataclass(frozen=True)
class MvpTopicBootstrapResult:
    job: EssayJob
    task_spec: TaskSpecification
    source_results: list[SourceIngestionResult]
    topic_round: TopicIdeationRound

    @property
    def index_manifests(self) -> list[SourceIndexManifest]:
        return [result.index_manifest for result in self.source_results if result.index_manifest is not None]


@dataclass(frozen=True)
class TaskSpecResolutionResult:
    job: EssayJob
    task_spec: TaskSpecification


class MvpWorkflowBootstrapper:
    """Create the pre-topic MVP job state from assignment and uploaded source inputs."""

    def __init__(
        self,
        *,
        workflow: EssayWorkflow,
        task_parser: TaskSpecParser,
        task_store: TaskSpecStore,
        source_ingestion: SourceIngestionService,
        topic_ideation: TopicIdeationService | None = None,
        assignment_reader: AssignmentExtractor | None = None,
    ) -> None:
        self._workflow = workflow
        self._task_parser = task_parser
        self._task_store = task_store
        self._source_ingestion = source_ingestion
        self._topic_ideation = topic_ideation
        self._assignment_reader = assignment_reader or DocumentReader()

    def create_job_from_inputs(
        self,
        *,
        assignment_text: str | None = None,
        assignment_path: str | Path | None = None,
        source_paths: list[str | Path] | None = None,
        selected_prompt: str | None = None,
        job_id: str | None = None,
    ) -> MvpBootstrapResult:
        raw_assignment_text = self._read_assignment_text(
            assignment_text=assignment_text,
            assignment_path=assignment_path,
        )
        job = self._workflow.create_job(job_id=job_id)
        stage = "source_ingestion"

        try:
            source_results = [
                self._source_ingestion.ingest(source_path)
                for source_path in source_paths or []
            ]
            if source_results:
                self._workflow.attach_sources(
                    job_id=job.id,
                    source_ids=[result.source.id for result in source_results],
                )

            stage = "task_specification"
            task_spec = self._task_parser.parse(
                raw_assignment_text,
                task_id=f"{job.id}-task",
                source_document_ids=[result.source.id for result in source_results],
                selected_prompt=selected_prompt,
            )
            self._task_store.save(task_spec)
            job = self._workflow.attach_task_spec(job_id=job.id, task_spec_id=task_spec.id)
            if task_spec.blocking_questions:
                job = self._workflow.mark_blocked(
                    job_id=job.id,
                    stage="task_specification",
                    message="; ".join(task_spec.blocking_questions),
                )
        except Exception as exc:
            self._workflow.mark_error(job_id=job.id, stage=stage, message=str(exc))
            raise

        return MvpBootstrapResult(
            job=job,
            task_spec=task_spec,
            source_results=source_results,
        )

    def create_job_and_topic_round(
        self,
        *,
        assignment_text: str | None = None,
        assignment_path: str | Path | None = None,
        source_paths: list[str | Path] | None = None,
        selected_prompt: str | None = None,
        user_instruction: str | None = None,
        job_id: str | None = None,
        model: str | None = None,
    ) -> MvpTopicBootstrapResult:
        bootstrap = self.create_job_from_inputs(
            assignment_text=assignment_text,
            assignment_path=assignment_path,
            source_paths=source_paths,
            selected_prompt=selected_prompt,
            job_id=job_id,
        )
        if bootstrap.job.status == "blocked":
            message = bootstrap.job.error_state.message if bootstrap.job.error_state else "Workflow is blocked."
            raise WorkflowBlockedError(message)
        return self.generate_topic_round(
            job_id=bootstrap.job.id,
            task_spec=bootstrap.task_spec,
            source_results=bootstrap.source_results,
            user_instruction=user_instruction,
            model=model,
        )

    def generate_topic_round(
        self,
        *,
        job_id: str,
        task_spec: TaskSpecification,
        source_results: list[SourceIngestionResult],
        user_instruction: str | None = None,
        model: str | None = None,
    ) -> MvpTopicBootstrapResult:
        if self._topic_ideation is None:
            raise ValueError("topic_ideation service is required to generate a topic round")
        try:
            previous_candidates = self._workflow.get_previous_candidates(job_id)
            rejected_topics = self._workflow.get_rejected_topics(job_id)
            topic_result = self._topic_ideation.generate(
                task_spec,
                source_cards=[result.source_card for result in source_results],
                index_manifests=[
                    result.index_manifest for result in source_results if result.index_manifest is not None
                ],
                source_maps=[
                    result.source_map for result in source_results if result.source_map is not None
                ],
                previous_candidates=previous_candidates,
                rejected_topics=rejected_topics,
                user_instruction=user_instruction,
                model=model,
            )
            topic_round = self._workflow.record_topic_round(
                job_id=job_id,
                topic_result=topic_result,
                user_instruction=user_instruction,
                previous_candidates=previous_candidates,
            )
        except Exception as exc:
            self._workflow.mark_error(job_id=job_id, stage="topic_ideation", message=str(exc))
            raise
        return MvpTopicBootstrapResult(
            job=self._workflow.load_job(job_id),
            task_spec=task_spec,
            source_results=source_results,
            topic_round=topic_round,
        )

    def resolve_task_spec_block(
        self,
        *,
        job_id: str,
        selected_prompt: str | None = None,
        assignment_text: str | None = None,
    ) -> TaskSpecResolutionResult:
        job = self._workflow.load_job(job_id)
        if job.task_spec_id is None:
            raise ValueError("Cannot resolve task-spec block before task_spec_id is set.")
        current = self._task_store.load_latest(job.task_spec_id)
        raw_text = assignment_text.strip() if assignment_text is not None else current.raw_text
        if not raw_text:
            raise ValueError("Assignment text is empty.")
        task_spec = self._task_parser.parse(
            raw_text,
            task_id=current.id,
            version=current.version + 1,
            source_document_ids=current.source_document_ids,
            selected_prompt=selected_prompt or current.selected_prompt,
        )
        self._task_store.save(task_spec)
        job = self._workflow.attach_task_spec(job_id=job.id, task_spec_id=task_spec.id)
        if task_spec.blocking_questions:
            job = self._workflow.mark_blocked(
                job_id=job.id,
                stage="task_specification",
                message="; ".join(task_spec.blocking_questions),
            )
        return TaskSpecResolutionResult(job=job, task_spec=task_spec)

    def _read_assignment_text(
        self,
        *,
        assignment_text: str | None,
        assignment_path: str | Path | None,
    ) -> str:
        if (assignment_text is None) == (assignment_path is None):
            raise ValueError("Provide exactly one of assignment_text or assignment_path.")
        if assignment_text is not None:
            text = assignment_text.strip()
        else:
            path = Path(assignment_path)  # type: ignore[arg-type]
            if not path.exists():
                raise FileNotFoundError(f"assignment document not found: {path}")
            text = _extracted_text(self._assignment_reader.extract(path)).strip()
        if not text:
            raise ValueError("Assignment text is empty.")
        return text


def _extracted_text(result: DocumentExtractionResult) -> str:
    return "\n\n".join(page.text.strip() for page in result.pages if page.text.strip())
