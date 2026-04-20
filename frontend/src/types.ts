export interface SourceUploadResponse {
  source_id: string;
  title: string;
  source_type: string;
  page_count: number;
  chunk_count: number;
  text_quality: string;
  warnings: string[];
}

export interface AssignmentExtractResponse {
  text: string;
  page_count: number;
  extraction_method: string;
}

export interface CreateJobResponse {
  job_id: string;
  task_spec_id: string;
  blocking_questions: string[];
  warnings: string[];
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  current_stage: string;
  selected_topic_id: string | null;
  draft_id: string | null;
  error: string | null;
}

export interface TopicSourceLead {
  source_id: string;
  chunk_count: number;
}

export interface CandidateTopic {
  topic_id: string;
  title: string;
  research_question: string;
  tentative_thesis_direction: string;
  rationale: string;
  fit_score: number;
  evidence_score: number;
  originality_score: number;
  source_leads: TopicSourceLead[];
}

export interface TopicsGenerateResponse {
  job_id: string;
  round_number: number;
  candidates: CandidateTopic[];
  blocking_questions: string[];
}

export interface SectionSourceEntry {
  section_id: string;
  heading: string;
  note_ids: string[];
  source_ids: string[];
}

export interface ValidationSummary {
  passes: boolean;
  overall_quality: number;
  unsupported_claim_count: number;
  revision_suggestions: string[];
}

export interface ExportResponse {
  job_id: string;
  draft_id: string;
  content: string;
  section_source_map: SectionSourceEntry[];
  bibliography_candidates: string[];
  validation: ValidationSummary;
}

export interface SSEEvent {
  event: string;
  stage?: string;
  passes?: boolean;
  draft_id?: string;
  final_export_id?: string | null;
  message?: string;
}

export interface AppSettings {
  llm_model: string;
  model_task_spec: string;
  model_source_card: string;
  model_topic_ideation: string;
  model_research: string;
  model_drafting: string;
  model_drafting_revision: string;
  model_validation: string;
  ocr_tier: "small" | "medium" | "high";
  chunk_target_chars: number;
  chunk_overlap_chars: number;
  max_full_read_pages: number;
  min_text_chars_per_page: number;
}

export interface AppSettingsResponse extends AppSettings {
  llm_provider: string;
  api_key_configured: boolean;
}

export type StageStatus = "pending" | "running" | "done" | "error" | "skipped";

export interface PipelineStage {
  key: string;
  label: string;
  status: StageStatus;
}
