"""Singleton stores and services, wired once at startup."""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from llm.config import StageModelConfig
from llm.factory import make_client
from llm.logging_client import LoggingLLMClient

from essay_writer.jobs.storage import EssayJobStore
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.sources.ingestion import SourceIngestionService
from essay_writer.sources.storage import SourceStore
from essay_writer.task_spec.parser import TaskSpecParser
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.service import TopicIdeationService
from essay_writer.topic_ideation.retrieval import TopicEvidenceRetriever
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.research_planning.service import ResearchPlanningService
from essay_writer.research_planning.storage import ResearchPlanStore
from essay_writer.research.service import FinalTopicResearchService
from essay_writer.research.storage import ResearchStore
from essay_writer.outlining.service import ThesisOutlineService
from essay_writer.outlining.storage import ThesisOutlineStore
from essay_writer.drafting.service import DraftService
from essay_writer.drafting.storage import DraftStore
from essay_writer.drafting.revision import DraftRevisionService
from essay_writer.validation.service import ValidationService
from essay_writer.validation.storage import ValidationStore
from essay_writer.exporting.service import FinalExportService
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.workflow.mvp import MvpWorkflowRunner


DATA_DIR = Path(os.environ.get("ESSAY_DATA_DIR", "./data"))


@lru_cache(maxsize=1)
def get_llm_client():
    return make_client()


def _logged(stage: str):
    return LoggingLLMClient(get_llm_client(), stage=stage)


@lru_cache(maxsize=1)
def get_source_store() -> SourceStore:
    return SourceStore(DATA_DIR / "sources")


@lru_cache(maxsize=1)
def get_job_store() -> EssayJobStore:
    return EssayJobStore(DATA_DIR / "jobs")


@lru_cache(maxsize=1)
def get_topic_store() -> TopicRoundStore:
    return TopicRoundStore(DATA_DIR / "topics")


@lru_cache(maxsize=1)
def get_workflow() -> EssayWorkflow:
    return EssayWorkflow(get_job_store(), get_topic_store())


@lru_cache(maxsize=1)
def get_ingestion_service() -> SourceIngestionService:
    return SourceIngestionService(
        get_source_store(),
        llm_client=_logged("source_card"),
    )


@lru_cache(maxsize=1)
def get_task_spec_parser() -> TaskSpecParser:
    return TaskSpecParser(llm_client=_logged("task_spec"))


@lru_cache(maxsize=1)
def get_task_spec_store() -> TaskSpecStore:
    return TaskSpecStore(DATA_DIR / "task_specs")


@lru_cache(maxsize=1)
def get_topic_ideation_service() -> TopicIdeationService:
    return TopicIdeationService(_logged("topic_ideation"))


@lru_cache(maxsize=1)
def get_retriever() -> TopicEvidenceRetriever:
    return TopicEvidenceRetriever(get_source_store())


@lru_cache(maxsize=1)
def get_workflow_runner() -> MvpWorkflowRunner:
    model_config = StageModelConfig.from_env()
    return MvpWorkflowRunner(
        workflow=get_workflow(),
        retriever=get_retriever(),
        research_planning_service=ResearchPlanningService(),
        research_plan_store=ResearchPlanStore(DATA_DIR / "research_plans"),
        research_service=FinalTopicResearchService(_logged("research")),
        research_store=ResearchStore(DATA_DIR / "research"),
        outline_service=ThesisOutlineService(),
        outline_store=ThesisOutlineStore(DATA_DIR / "outlines"),
        draft_service=DraftService(_logged("drafting")),
        draft_store=DraftStore(DATA_DIR / "drafts"),
        validation_service=ValidationService(_logged("validation")),
        validation_store=ValidationStore(DATA_DIR / "validations"),
        revision_service=DraftRevisionService(_logged("drafting_revision")),
        export_service=FinalExportService(),
        export_store=FinalExportStore(DATA_DIR / "exports"),
        task_store=get_task_spec_store(),
        topic_store=get_topic_store(),
        source_store=get_source_store(),
        model_config=model_config,
    )
