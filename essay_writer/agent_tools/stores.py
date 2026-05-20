from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from essay_writer.drafting.storage import DraftStore
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.jobs.storage import EssayJobStore
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.outlining.storage import ThesisOutlineStore
from essay_writer.research.storage import ResearchStore
from essay_writer.research_planning.storage import ResearchPlanStore
from essay_writer.sources.access import SourceAccessService
from essay_writer.sources.access_schema import SourceAccessConfig
from essay_writer.sources.storage import SourceStore
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.retrieval import TopicEvidenceRetriever
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.validation.storage import ValidationStore
from essay_writer.writing_style.storage import (
    HumanWritingSampleStore,
    WritingStyleContentStore,
)


@dataclass(frozen=True)
class AgentStoreBundle:
    data_dir: Path
    source_store: SourceStore
    task_store: TaskSpecStore
    job_store: EssayJobStore
    topic_store: TopicRoundStore
    workflow: EssayWorkflow
    retriever: TopicEvidenceRetriever
    source_access: SourceAccessService
    research_plan_store: ResearchPlanStore
    research_store: ResearchStore
    outline_store: ThesisOutlineStore
    draft_store: DraftStore
    validation_store: ValidationStore
    export_store: FinalExportStore
    writing_style_sample_store: HumanWritingSampleStore
    writing_style_content_store: WritingStyleContentStore

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "AgentStoreBundle":
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)

        source_store = SourceStore(root / "sources")
        task_store = TaskSpecStore(root / "task_specs")
        job_store = EssayJobStore(root / "jobs")
        topic_store = TopicRoundStore(root / "topics")
        workflow = EssayWorkflow(job_store, topic_store)
        retriever = TopicEvidenceRetriever(source_store)
        source_access = SourceAccessService(
            source_store,
            config=SourceAccessConfig(),
        )

        return cls(
            data_dir=root,
            source_store=source_store,
            task_store=task_store,
            job_store=job_store,
            topic_store=topic_store,
            workflow=workflow,
            retriever=retriever,
            source_access=source_access,
            research_plan_store=ResearchPlanStore(root / "research_plans"),
            research_store=ResearchStore(root / "research"),
            outline_store=ThesisOutlineStore(root / "outlines"),
            draft_store=DraftStore(root / "drafts"),
            validation_store=ValidationStore(root / "validations"),
            export_store=FinalExportStore(root / "exports"),
            writing_style_sample_store=HumanWritingSampleStore(
                root / "writing_style" / "samples"
            ),
            writing_style_content_store=WritingStyleContentStore(
                root / "writing_style" / "content"
            ),
        )
