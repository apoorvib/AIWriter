import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import StageTracker from "../components/StageTracker";
import EssayViewer from "../components/EssayViewer";
import { getExport, openJobEvents, runPipeline } from "../api";
import type { ExportResponse, PipelineStage, SSEEvent } from "../types";

const INITIAL_STAGES: PipelineStage[] = [
  { key: "research_planning", label: "Plan", status: "pending" },
  { key: "research", label: "Research", status: "pending" },
  { key: "outlining", label: "Outline", status: "pending" },
  { key: "drafting", label: "Draft", status: "pending" },
  { key: "validation", label: "Validate", status: "pending" },
  { key: "revision", label: "Revise", status: "pending" },
  { key: "export", label: "Export", status: "pending" },
];

const STAGE_LABELS: Record<string, string> = {
  research_planning: "Research Planning",
  research: "Research",
  outlining: "Outlining",
  drafting: "Drafting",
  validation: "Validation",
  revision: "Revision",
  export: "Export",
  workflow: "Workflow",
  starting: "Pipeline startup",
};

interface PipelineError {
  message: string;
  detail: string | null;
  stage: string | null;
  errorType: string | null;
}

function PipelineErrorPanel({ err }: { err: PipelineError }) {
  const [showDetail, setShowDetail] = useState(false);
  const stageLabel = err.stage ? (STAGE_LABELS[err.stage] ?? err.stage) : null;

  return (
    <div className="pipeline-error-panel">
      <div className="pipeline-error-header">
        <span className="pipeline-error-icon">✕</span>
        <span className="pipeline-error-title">
          {stageLabel ? `Failed during ${stageLabel}` : "Pipeline failed"}
        </span>
        {err.errorType && (
          <code className="pipeline-error-type">{err.errorType}</code>
        )}
      </div>
      <p className="pipeline-error-message">{err.message}</p>
      {err.detail && err.detail !== err.message && (
        <div className="pipeline-error-detail-toggle">
          <button
            className="text-button"
            onClick={() => setShowDetail((v) => !v)}
          >
            {showDetail ? "Hide technical detail" : "Show technical detail"}
          </button>
          {showDetail && (
            <pre className="pipeline-error-detail">{err.detail}</pre>
          )}
        </div>
      )}
    </div>
  );
}

export default function PipelineView() {
  const { jobId } = useParams<{ jobId: string }>();
  const [stages, setStages] = useState<PipelineStage[]>(INITIAL_STAGES);
  const [essay, setEssay] = useState<ExportResponse | null>(null);
  const [pipelineError, setPipelineError] = useState<PipelineError | null>(null);
  const [progressMsg, setProgressMsg] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [externalSearchAllowed, setExternalSearchAllowed] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  function updateStage(key: string, status: PipelineStage["status"]) {
    setStages((prev) => prev.map((s) => (s.key === key ? { ...s, status } : s)));
  }

  useEffect(() => () => esRef.current?.close(), []);

  async function handleStart() {
    if (!jobId || started) return;
    setStarted(true);
    setPipelineError(null);

    try {
      await runPipeline(jobId, externalSearchAllowed);
      const es = openJobEvents(jobId);
      esRef.current = es;

      es.onmessage = async (e: MessageEvent) => {
        const payload: SSEEvent = JSON.parse(e.data as string);
        if (payload.event === "ping") return;

        if (payload.event === "progress") {
          setProgressMsg(payload.message ?? null);
        } else if (payload.event === "stage_start" && payload.stage) {
          updateStage(payload.stage, "running");
          setProgressMsg(null);
        } else if (payload.event === "stage_done" && payload.stage) {
          updateStage(payload.stage, "done");
          setProgressMsg(null);
        } else if (payload.event === "complete") {
          es.close();
          setProgressMsg(null);
          if (payload.passes) {
            setStages((prev) =>
              prev.map((stage) =>
                stage.key === "revision" && stage.status === "pending"
                  ? { ...stage, status: "skipped" }
                  : stage
              )
            );
          }
          try {
            const data = await getExport(jobId);
            setEssay(data);
          } catch {
            setPipelineError({
              message: "Pipeline finished but the export could not be loaded.",
              detail: null,
              stage: "export",
              errorType: null,
            });
          }
        } else if (payload.event === "error") {
          setProgressMsg(null);
          es.close();
          setStages((prev) => prev.map((s) => (s.status === "running" ? { ...s, status: "error" } : s)));
          setPipelineError({
            message: payload.message ?? "Unknown pipeline error.",
            detail: payload.detail ?? null,
            stage: payload.stage ?? null,
            errorType: payload.error_type ?? null,
          });
        }
      };

      es.onerror = () => {
        setPipelineError({
          message: "Lost connection to pipeline events. The pipeline may still be running — refresh to check.",
          detail: null,
          stage: null,
          errorType: "ConnectionError",
        });
        es.close();
      };
    } catch (e) {
      setPipelineError({
        message: e instanceof Error ? e.message : "Failed to start pipeline.",
        detail: null,
        stage: "starting",
        errorType: e instanceof Error ? e.constructor.name : null,
      });
      setStarted(false);
    }
  }

  return (
    <div className="page page-wide">
      <header className="page-header">
        <p className="eyebrow">Job {jobId}</p>
        <h1>Run the essay pipeline</h1>
        <p className="subtitle">Research, outline, draft, validate, revise if needed, and export.</p>
      </header>

      <section className="run-panel">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={externalSearchAllowed}
            onChange={(e) => setExternalSearchAllowed(e.target.checked)}
            disabled={started}
          />
          <span>Allow external web search during research when the provider supports it</span>
        </label>
        <button className="btn-primary" type="button" disabled={started} onClick={handleStart}>
          {started ? "Pipeline running..." : "Start pipeline"}
        </button>
      </section>

      <StageTracker stages={stages} />

      {progressMsg && (
        <p className="progress-msg">{progressMsg}</p>
      )}

      {pipelineError && <PipelineErrorPanel err={pipelineError} />}

      {essay && (
        <div className="essay-section">
          <h2>Essay</h2>
          <EssayViewer data={essay} />
        </div>
      )}

      {started && !essay && !pipelineError && (
        <p className="running-hint">The pipeline is running. Long source sets can take a few minutes.</p>
      )}
    </div>
  );
}
