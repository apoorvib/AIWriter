"""Pydantic response/request models for the API layer."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


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
    writing_style_sample_ids: list[str] = Field(default_factory=list)


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
    final_export_id: str | None = None
    writing_style_sample_ids: list[str] = Field(default_factory=list)
    error: str | None


class WritingSampleResponse(BaseModel):
    sample_id: str
    title: str
    source_filename: str
    source_type: str
    page_count: int
    word_count: int
    warnings: list[str] = Field(default_factory=list)


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


class ValidationDiagnosticResponse(BaseModel):
    location: str
    issue_type: str
    evidence: str
    severity: str
    action: str


class ValidationSummary(BaseModel):
    passes: bool
    overall_quality: float
    unsupported_claim_count: int
    diagnostics: list[ValidationDiagnosticResponse] = Field(default_factory=list)
    revision_suggestions: list[str]


class DraftSummaryResponse(BaseModel):
    draft_id: str
    version: int
    origin: str
    created_by: str
    created_at: str
    parent_draft_id: str | None = None
    parent_export_id: str | None = None
    manual_request_id: str | None = None
    user_instruction: str | None = None
    selected_lenses: list[str] = Field(default_factory=list)
    preview: str


class DraftResponse(BaseModel):
    job_id: str
    draft_id: str
    version: int
    selected_topic_id: str
    content: str
    outline_id: str | None = None
    citation_style: str | None = None
    section_source_map: list[SectionSourceEntry] = Field(default_factory=list)
    bibliography_candidates: list[str] = Field(default_factory=list)
    known_weak_spots: list[str] = Field(default_factory=list)
    origin: str
    created_by: str
    parent_draft_id: str | None = None
    parent_export_id: str | None = None
    manual_request_id: str | None = None
    user_instruction: str | None = None
    selected_lenses: list[str] = Field(default_factory=list)
    created_at: str


class ExportSummaryResponse(BaseModel):
    export_id: str
    draft_id: str
    draft_version: int | None = None
    created_at: str
    preview: str


class ExportResponse(BaseModel):
    job_id: str
    export_id: str
    draft_id: str
    draft_version: int | None = None
    content: str
    draft_content: str
    section_source_map: list[SectionSourceEntry]
    bibliography_candidates: list[str]
    validation: ValidationSummary


class SaveUserEditRequest(BaseModel):
    base_draft_id: str | None = None
    base_export_id: str | None = None
    content: str


class DeterministicSentenceRunResponse(BaseModel):
    sentence_count: int
    avg_word_count: float


class DeterministicParagraphProfileResponse(BaseModel):
    paragraph_count: int
    shortest_word_count: int
    longest_word_count: int
    longest_to_shortest_ratio: float


class VocabHitResponse(BaseModel):
    word: str
    count: int


class AntiAiSummaryResponse(BaseModel):
    word_count: int
    em_dash_count: int
    en_dash_count: int
    decorative_hyphen_pause_count: int
    colon_explanation_pattern_count: int
    triplet_contrastive_combo_count: int
    clustered_triplet_count: int
    participial_phrase_count: int
    participial_phrase_rate: float
    contrastive_negation_count: int
    bad_conclusion_opener: bool
    concrete_engagement_present: bool
    paragraph_length_variance_warning: bool
    mechanical_burstiness_count: int
    tier1_vocab_hits: list[VocabHitResponse] = Field(default_factory=list)
    signposting_hits: list[str] = Field(default_factory=list)
    consecutive_similar_sentence_runs: list[DeterministicSentenceRunResponse] = Field(default_factory=list)
    paragraph_length_profile: DeterministicParagraphProfileResponse | None = None


class ToneAlignmentConflictResponse(BaseModel):
    issue_type: str
    anti_ai_signal: str
    tone_signal: str
    resolution: str
    rationale: str


class ToneAlignmentSummaryResponse(BaseModel):
    overall_alignment: float
    requires_revision: bool
    matched_habits: list[str] = Field(default_factory=list)
    mismatched_habits: list[str] = Field(default_factory=list)
    preserve_points: list[str] = Field(default_factory=list)
    revision_targets: list[str] = Field(default_factory=list)
    anti_ai_conflicts: list[ToneAlignmentConflictResponse] = Field(default_factory=list)


class ManualRevisionCreateRequest(BaseModel):
    source_draft_id: str
    mode: Literal["review_only", "revise"]
    instruction: str | None = None
    selected_lenses: list[Literal["evidence", "citations", "assignment_fit", "length", "tone", "anti_ai"]] = Field(
        default_factory=list
    )


class ManualRevisionRunSummaryResponse(BaseModel):
    run_id: str
    request_id: str
    source_draft_id: str
    source_draft_version: int | None = None
    result_draft_id: str | None = None
    result_draft_version: int | None = None
    mode: Literal["review_only", "revise"]
    selected_lenses: list[str] = Field(default_factory=list)
    status: str
    created_at: str


class ManualRevisionRunResponse(BaseModel):
    run_id: str
    request_id: str
    source_draft_id: str
    source_draft_version: int | None = None
    result_draft_id: str | None = None
    result_draft_version: int | None = None
    mode: Literal["review_only", "revise"]
    instruction: str | None = None
    selected_lenses: list[str] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: str
    created_at: str
    pre_revision_validation: ValidationSummary | None = None
    pre_revision_tone_alignment: ToneAlignmentSummaryResponse | None = None
    pre_revision_anti_ai: AntiAiSummaryResponse | None = None
    post_revision_validation: ValidationSummary | None = None
    post_revision_tone_alignment: ToneAlignmentSummaryResponse | None = None
    post_revision_anti_ai: AntiAiSummaryResponse | None = None


class AppSettings(BaseModel):
    llm_model: str = ""
    model_task_spec: str = ""
    model_source_card: str = ""
    model_topic_ideation: str = ""
    model_research: str = ""
    model_outlining: str = ""
    model_drafting: str = ""
    model_drafting_revision: str = ""
    model_drafting_style: str = ""
    model_validation: str = ""
    max_tokens_task_spec: int = 0
    max_tokens_source_card: int = 0
    max_tokens_topic_ideation: int = 0
    max_tokens_research: int = 0
    max_tokens_outlining: int = 0
    max_tokens_drafting: int = 0
    max_tokens_drafting_revision: int = 0
    max_tokens_drafting_style: int = 0
    max_tokens_validation: int = 0
    ocr_tier: Literal["small", "medium", "high"] = "small"
    chunk_target_chars: int = 3000
    chunk_overlap_chars: int = 300
    max_full_read_pages: int = 30
    min_text_chars_per_page: int = 300


class AppSettingsResponse(AppSettings):
    llm_provider: str
    api_key_configured: bool
