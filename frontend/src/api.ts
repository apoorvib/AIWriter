import type {
  AssignmentExtractResponse,
  SourceUploadResponse,
  CreateJobResponse,
  TopicsGenerateResponse,
  ExportResponse,
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
  sourceIds: string[]
): Promise<CreateJobResponse> {
  return request<CreateJobResponse>("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assignment_text: assignmentText, source_ids: sourceIds }),
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

export function getExport(jobId: string): Promise<ExportResponse> {
  return request<ExportResponse>(`/jobs/${jobId}/export`);
}

export function openJobEvents(jobId: string): EventSource {
  return new EventSource(`${BASE}/jobs/${jobId}/events`);
}
