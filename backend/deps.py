"""Singleton stores and services, wired once at startup."""
from __future__ import annotations

import json
import os
from pathlib import Path
from functools import lru_cache

from llm.config import StageMaxTokensConfig, StageModelConfig
from llm.factory import make_client
from llm.logging_client import LoggingLLMClient

from essay_writer.jobs.storage import EssayJobStore
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.sources.ingestion import SourceIngestionService
from essay_writer.sources.access import SourceAccessService
from essay_writer.sources.access_schema import SourceAccessConfig
from essay_writer.sources.schema import SourceIngestionConfig
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
from essay_writer.drafting.style_revision import FinalStyleRevisionService
from essay_writer.validation.service import ValidationService
from essay_writer.validation.storage import ValidationStore
from essay_writer.exporting.service import FinalExportService
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.workflow.mvp import MvpWorkflowRunner
from pdf_pipeline.ocr import OcrTier

from backend.schemas import AppSettings


DATA_DIR = Path(os.environ.get("ESSAY_DATA_DIR", "./data"))
_SETTINGS_PATH = DATA_DIR / "settings.json"


def load_settings() -> AppSettings:
    if _SETTINGS_PATH.exists():
        try:
            return AppSettings.model_validate(json.loads(_SETTINGS_PATH.read_text()))
        except Exception:
            pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(settings.model_dump_json(indent=2))


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


def _max_tokens_config_from_settings() -> StageMaxTokensConfig:
    s = load_settings()
    env = StageMaxTokensConfig.from_env()
    def pick(settings_val: int, env_val: int) -> int:
        return settings_val if settings_val > 0 else env_val
    return StageMaxTokensConfig(
        task_spec=pick(s.max_tokens_task_spec, env.task_spec),
        source_card=pick(s.max_tokens_source_card, env.source_card),
        topic_ideation=pick(s.max_tokens_topic_ideation, env.topic_ideation),
        research=pick(s.max_tokens_research, env.research),
        outlining=pick(s.max_tokens_outlining, env.outlining),
        drafting=pick(s.max_tokens_drafting, env.drafting),
        drafting_revision=pick(s.max_tokens_drafting_revision, env.drafting_revision),
        drafting_style=pick(s.max_tokens_drafting_style, env.drafting_style),
        validation=pick(s.max_tokens_validation, env.validation),
    )


def get_ingestion_service() -> SourceIngestionService:
    s = load_settings()
    mc = _model_config_from_settings()
    mt = _max_tokens_config_from_settings()
    config = SourceIngestionConfig(
        ocr_tier=OcrTier(s.ocr_tier),
        chunk_target_chars=s.chunk_target_chars,
        chunk_overlap_chars=s.chunk_overlap_chars,
        max_full_read_pages=s.max_full_read_pages,
        min_text_chars_per_page=s.min_text_chars_per_page,
    )
    return SourceIngestionService(
        get_source_store(),
        config=config,
        llm_client=_logged("source_card"),
        source_card_max_tokens=mt.source_card,
        source_card_model=mc.source_card,
    )


@lru_cache(maxsize=1)
def get_task_spec_parser() -> TaskSpecParser:
    mc = _model_config_from_settings()
    mt = _max_tokens_config_from_settings()
    return TaskSpecParser(llm_client=_logged("task_spec"), max_tokens=mt.task_spec, model=mc.task_spec)


@lru_cache(maxsize=1)
def get_task_spec_store() -> TaskSpecStore:
    return TaskSpecStore(DATA_DIR / "task_specs")


@lru_cache(maxsize=1)
def get_topic_ideation_service() -> TopicIdeationService:
    mc = _model_config_from_settings()
    mt = _max_tokens_config_from_settings()
    return TopicIdeationService(_logged("topic_ideation"), max_tokens=mt.topic_ideation, model=mc.topic_ideation)


@lru_cache(maxsize=1)
def get_retriever() -> TopicEvidenceRetriever:
    return TopicEvidenceRetriever(get_source_store())


@lru_cache(maxsize=1)
def get_source_access_service() -> SourceAccessService:
    return SourceAccessService(get_source_store(), config=SourceAccessConfig.from_env())


def _model_config_from_settings() -> StageModelConfig:
    s = load_settings()
    settings_default = s.llm_model.strip() or None
    env_default = os.environ.get("LLM_MODEL") or None

    def pick(settings_val: str, env_key: str) -> str | None:
        return settings_val.strip() or os.environ.get(env_key) or settings_default or env_default or None

    return StageModelConfig(
        task_spec=pick(s.model_task_spec, "ESSAY_MODEL_TASK_SPEC"),
        source_card=pick(s.model_source_card, "ESSAY_MODEL_SOURCE_CARD"),
        topic_ideation=pick(s.model_topic_ideation, "ESSAY_MODEL_TOPIC_IDEATION"),
        research=pick(s.model_research, "ESSAY_MODEL_RESEARCH"),
        outlining=pick(s.model_outlining, "ESSAY_MODEL_OUTLINING"),
        drafting=pick(s.model_drafting, "ESSAY_MODEL_DRAFTING"),
        drafting_revision=pick(s.model_drafting_revision, "ESSAY_MODEL_DRAFTING_REVISION"),
        drafting_style=pick(s.model_drafting_style, "ESSAY_MODEL_DRAFTING_STYLE"),
        validation=pick(s.model_validation, "ESSAY_MODEL_VALIDATION"),
    )


@lru_cache(maxsize=1)
def get_workflow_runner() -> MvpWorkflowRunner:
    model_config = _model_config_from_settings()
    mt = _max_tokens_config_from_settings()
    return MvpWorkflowRunner(
        workflow=get_workflow(),
        retriever=get_retriever(),
        research_planning_service=ResearchPlanningService(),
        research_plan_store=ResearchPlanStore(DATA_DIR / "research_plans"),
        research_service=FinalTopicResearchService(_logged("research"), max_tokens=mt.research),
        research_store=ResearchStore(DATA_DIR / "research"),
        outline_service=ThesisOutlineService(llm_client=_logged("outlining"), max_tokens=mt.outlining),
        outline_store=ThesisOutlineStore(DATA_DIR / "outlines"),
        draft_service=DraftService(_logged("drafting"), max_tokens=mt.drafting),
        draft_store=DraftStore(DATA_DIR / "drafts"),
        validation_service=ValidationService(_logged("validation"), max_tokens=mt.validation),
        validation_store=ValidationStore(DATA_DIR / "validations"),
        revision_service=DraftRevisionService(_logged("drafting_revision"), max_tokens=mt.drafting_revision),
        style_revision_service=FinalStyleRevisionService(_logged("drafting_style"), max_tokens=mt.drafting_style),
        export_service=FinalExportService(),
        export_store=FinalExportStore(DATA_DIR / "exports"),
        task_store=get_task_spec_store(),
        topic_store=get_topic_store(),
        source_store=get_source_store(),
        source_access_service=get_source_access_service(),
        model_config=model_config,
    )
