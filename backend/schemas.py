"""Pydantic response/request models for the API layer."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class SourceUploadResponse(BaseModel):
    source_id: str
    title: str
    source_type: str
    page_count: int
    chunk_count: int
    text_quality: str
    warnings: list[str]


class AssignmentExtractResponse(BaseModel):
    text: str
    page_count: int
    extraction_method: str


class CreateJobRequest(BaseModel):
    assignment_text: str
    source_ids: list[str]


class CreateJobResponse(BaseModel):
    job_id: str
    task_spec_id: str
    blocking_questions: list[str]
    warnings: list[str]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    current_stage: str
    selected_topic_id: str | None
    draft_id: str | None
    error: str | None


class TopicSourceLead(BaseModel):
    source_id: str
    chunk_count: int


class CandidateTopicResponse(BaseModel):
    topic_id: str
    title: str
    research_question: str
    tentative_thesis_direction: str
    rationale: str
    fit_score: float
    evidence_score: float
    originality_score: float
    source_leads: list[TopicSourceLead]


class TopicsGenerateResponse(BaseModel):
    job_id: str
    round_number: int
    candidates: list[CandidateTopicResponse]
    blocking_questions: list[str]


class TopicsGenerateRequest(BaseModel):
    user_instruction: str | None = None


class TopicSelectRequest(BaseModel):
    topic_id: str
    round_number: int


class TopicSelectResponse(BaseModel):
    job_id: str
    selected_topic_id: str
    status: str


class TopicRejectRequest(BaseModel):
    topic_id: str
    round_number: int
    reason: str


class TopicRejectResponse(BaseModel):
    job_id: str
    topic_id: str
    reason: str


class RunPipelineRequest(BaseModel):
    external_search_allowed: bool = False


class RunPipelineResponse(BaseModel):
    job_id: str
    status: str


class SectionSourceEntry(BaseModel):
    section_id: str
    heading: str
    note_ids: list[str]
    source_ids: list[str]


class ValidationSummary(BaseModel):
    passes: bool
    overall_quality: float
    unsupported_claim_count: int
    revision_suggestions: list[str]


class ExportResponse(BaseModel):
    job_id: str
    draft_id: str
    content: str
    section_source_map: list[SectionSourceEntry]
    bibliography_candidates: list[str]
    validation: ValidationSummary
