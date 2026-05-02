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

export interface WritingSample {
  sample_id: string;
  title: string;
  source_filename: string;
  source_type: string;
  page_count: number;
  word_count: number;
  warnings: string[];
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  current_stage: string;
  selected_topic_id: string | null;
  draft_id: string | null;
  final_export_id: string | null;
  writing_style_sample_ids: string[];
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
  diagnostics: ValidationDiagnostic[];
  revision_suggestions: string[];
}

export interface ValidationDiagnostic {
  location: string;
  issue_type: string;
  evidence: string;
  severity: string;
  action: string;
}

export interface DraftSummary {
  draft_id: string;
  version: number;
  origin: string;
  created_by: string;
  created_at: string;
  parent_draft_id: string | null;
  parent_export_id: string | null;
  manual_request_id: string | null;
  user_instruction: string | null;
  selected_lenses: string[];
  preview: string;
}

export interface DraftResponse {
  job_id: string;
  draft_id: string;
  version: number;
  selected_topic_id: string;
  content: string;
  outline_id: string | null;
  citation_style: string | null;
  section_source_map: SectionSourceEntry[];
  bibliography_candidates: string[];
  known_weak_spots: string[];
  origin: string;
  created_by: string;
  parent_draft_id: string | null;
  parent_export_id: string | null;
  manual_request_id: string | null;
  user_instruction: string | null;
  selected_lenses: string[];
  created_at: string;
}

export interface ExportSummary {
  export_id: string;
  draft_id: string;
  draft_version: number | null;
  created_at: string;
  preview: string;
}

export interface ExportResponse {
  job_id: string;
  export_id: string;
  draft_id: string;
  draft_version: number | null;
  content: string;
  draft_content: string;
  section_source_map: SectionSourceEntry[];
  bibliography_candidates: string[];
  validation: ValidationSummary;
}

export interface SentenceRun {
  sentence_count: number;
  avg_word_count: number;
}

export interface ParagraphLengthProfile {
  paragraph_count: number;
  shortest_word_count: number;
  longest_word_count: number;
  longest_to_shortest_ratio: number;
}

export interface VocabHit {
  word: string;
  count: number;
}

export interface AntiAiSummary {
  word_count: number;
  em_dash_count: number;
  en_dash_count: number;
  decorative_hyphen_pause_count: number;
  colon_explanation_pattern_count: number;
  triplet_contrastive_combo_count: number;
  clustered_triplet_count: number;
  participial_phrase_count: number;
  participial_phrase_rate: number;
  contrastive_negation_count: number;
  bad_conclusion_opener: boolean;
  concrete_engagement_present: boolean;
  paragraph_length_variance_warning: boolean;
  mechanical_burstiness_count: number;
  tier1_vocab_hits: VocabHit[];
  signposting_hits: string[];
  consecutive_similar_sentence_runs: SentenceRun[];
  paragraph_length_profile: ParagraphLengthProfile | null;
}

export interface ToneAlignmentConflict {
  issue_type: string;
  anti_ai_signal: string;
  tone_signal: string;
  resolution: string;
  rationale: string;
}

export interface ToneAlignmentSummary {
  overall_alignment: number;
  requires_revision: boolean;
  matched_habits: string[];
  mismatched_habits: string[];
  preserve_points: string[];
  revision_targets: string[];
  anti_ai_conflicts: ToneAlignmentConflict[];
}

export type ManualLens =
  | "evidence"
  | "citations"
  | "assignment_fit"
  | "length"
  | "tone"
  | "anti_ai";

export type ManualMode = "review_only" | "revise";

export interface ManualRevisionRunSummary {
  run_id: string;
  request_id: string;
  source_draft_id: string;
  source_draft_version: number | null;
  result_draft_id: string | null;
  result_draft_version: number | null;
  mode: ManualMode;
  selected_lenses: string[];
  status: string;
  created_at: string;
}

export interface ManualRevisionRunResponse {
  run_id: string;
  request_id: string;
  source_draft_id: string;
  source_draft_version: number | null;
  result_draft_id: string | null;
  result_draft_version: number | null;
  mode: ManualMode;
  instruction: string | null;
  selected_lenses: string[];
  change_summary: string[];
  warnings: string[];
  status: string;
  created_at: string;
  pre_revision_validation: ValidationSummary | null;
  pre_revision_tone_alignment: ToneAlignmentSummary | null;
  pre_revision_anti_ai: AntiAiSummary | null;
  post_revision_validation: ValidationSummary | null;
  post_revision_tone_alignment: ToneAlignmentSummary | null;
  post_revision_anti_ai: AntiAiSummary | null;
}

export interface SSEEvent {
  event: string;
  stage?: string;
  passes?: boolean;
  draft_id?: string;
  final_export_id?: string | null;
  message?: string;
  detail?: string;
  error_type?: string;
}

export interface AppSettings {
  llm_model: string;
  model_task_spec: string;
  model_source_card: string;
  model_topic_ideation: string;
  model_research: string;
  model_outlining: string;
  model_drafting: string;
  model_drafting_revision: string;
  model_drafting_style: string;
  model_validation: string;
  max_tokens_task_spec: number;
  max_tokens_source_card: number;
  max_tokens_topic_ideation: number;
  max_tokens_research: number;
  max_tokens_outlining: number;
  max_tokens_drafting: number;
  max_tokens_drafting_revision: number;
  max_tokens_drafting_style: number;
  max_tokens_validation: number;
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
