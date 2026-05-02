import type {
  AppSettings,
  AppSettingsResponse,
  AssignmentExtractResponse,
  CreateJobResponse,
  DraftResponse,
  DraftSummary,
  ExportResponse,
  ExportSummary,
  JobStatusResponse,
  ManualLens,
  ManualMode,
  ManualRevisionRunResponse,
  ManualRevisionRunSummary,
  SourceUploadResponse,
  TopicsGenerateResponse,
  WritingSample,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export function uploadSource(file: File): Promise<SourceUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<SourceUploadResponse>("/sources/upload", {
    method: "POST",
    body: form,
  });
}

export function extractAssignment(file: File): Promise<AssignmentExtractResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<AssignmentExtractResponse>("/sources/assignment/extract", {
    method: "POST",
    body: form,
  });
}

export function createJob(
  assignmentText: string,
  sourceIds: string[],
  writingStyleSampleIds: string[] = [],
): Promise<CreateJobResponse> {
  return request<CreateJobResponse>("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      assignment_text: assignmentText,
      source_ids: sourceIds,
      writing_style_sample_ids: writingStyleSampleIds,
    }),
  });
}

export function generateTopics(
  jobId: string,
  userInstruction?: string
): Promise<TopicsGenerateResponse> {
  return request<TopicsGenerateResponse>(`/jobs/${jobId}/topics/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_instruction: userInstruction ?? null }),
  });
}

export function selectTopic(
  jobId: string,
  topicId: string,
  roundNumber: number
): Promise<void> {
  return request<void>(`/jobs/${jobId}/topics/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic_id: topicId, round_number: roundNumber }),
  });
}

export function rejectTopic(
  jobId: string,
  topicId: string,
  roundNumber: number,
  reason: string
): Promise<void> {
  return request<void>(`/jobs/${jobId}/topics/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic_id: topicId, round_number: roundNumber, reason }),
  });
}

export function runPipeline(jobId: string, externalSearchAllowed: boolean): Promise<void> {
  return request<void>(`/jobs/${jobId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ external_search_allowed: externalSearchAllowed }),
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return request<JobStatusResponse>(`/jobs/${jobId}`);
}

export function listDrafts(jobId: string): Promise<DraftSummary[]> {
  return request<DraftSummary[]>(`/jobs/${jobId}/drafts`);
}

export function getDraft(jobId: string, version: number): Promise<DraftResponse> {
  return request<DraftResponse>(`/jobs/${jobId}/drafts/${version}`);
}

export function saveUserEdit(
  jobId: string,
  payload: { content: string; baseDraftId?: string | null; baseExportId?: string | null }
): Promise<DraftResponse> {
  return request<DraftResponse>(`/jobs/${jobId}/drafts/save-user-edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: payload.content,
      base_draft_id: payload.baseDraftId ?? null,
      base_export_id: payload.baseExportId ?? null,
    }),
  });
}

export function getExport(jobId: string): Promise<ExportResponse> {
  return request<ExportResponse>(`/jobs/${jobId}/export`);
}

export function listExports(jobId: string): Promise<ExportSummary[]> {
  return request<ExportSummary[]>(`/jobs/${jobId}/exports`);
}

export function getExportById(jobId: string, exportId: string): Promise<ExportResponse> {
  return request<ExportResponse>(`/jobs/${jobId}/exports/${exportId}`);
}

export function listManualRevisionRuns(jobId: string): Promise<ManualRevisionRunSummary[]> {
  return request<ManualRevisionRunSummary[]>(`/jobs/${jobId}/manual-revision-runs`);
}

export function getManualRevisionRun(jobId: string, runId: string): Promise<ManualRevisionRunResponse> {
  return request<ManualRevisionRunResponse>(`/jobs/${jobId}/manual-revision-runs/${runId}`);
}

export function createManualRevisionRun(
  jobId: string,
  payload: {
    sourceDraftId: string;
    mode: ManualMode;
    instruction?: string | null;
    selectedLenses: ManualLens[];
  }
): Promise<ManualRevisionRunResponse> {
  return request<ManualRevisionRunResponse>(`/jobs/${jobId}/manual-revision-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_draft_id: payload.sourceDraftId,
      mode: payload.mode,
      instruction: payload.instruction ?? null,
      selected_lenses: payload.selectedLenses,
    }),
  });
}

export function openJobEvents(jobId: string): EventSource {
  return new EventSource(`${BASE}/jobs/${jobId}/events`);
}

export function listWritingSamples(): Promise<WritingSample[]> {
  return request<WritingSample[]>("/writing-style/samples");
}

export function uploadWritingSample(file: File): Promise<WritingSample> {
  const form = new FormData();
  form.append("file", file);
  return request<WritingSample>("/writing-style/samples/upload", {
    method: "POST",
    body: form,
  });
}

export function getSettings(): Promise<AppSettingsResponse> {
  return request<AppSettingsResponse>("/settings");
}

export function updateSettings(settings: AppSettings): Promise<AppSettingsResponse> {
  return request<AppSettingsResponse>("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}
