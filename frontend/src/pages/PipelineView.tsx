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

export default function PipelineView() {
  const { jobId } = useParams<{ jobId: string }>();
  const [stages, setStages] = useState<PipelineStage[]>(INITIAL_STAGES);
  const [essay, setEssay] = useState<ExportResponse | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
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

        if (payload.event === "stage_start" && payload.stage) {
          updateStage(payload.stage, "running");
        } else if (payload.event === "stage_done" && payload.stage) {
          updateStage(payload.stage, "done");
        } else if (payload.event === "complete") {
          es.close();
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
            setPipelineError("Pipeline finished, but no export is available.");
          }
        } else if (payload.event === "error") {
          setPipelineError(payload.message ?? "Unknown pipeline error.");
          es.close();
          setStages((prev) => prev.map((s) => (s.status === "running" ? { ...s, status: "error" } : s)));
        }
      };

      es.onerror = () => {
        setPipelineError("Lost connection to pipeline events.");
        es.close();
      };
    } catch (e) {
      setPipelineError(e instanceof Error ? e.message : "Failed to start pipeline.");
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

      {pipelineError && (
        <div className="error-box">
          <strong>Pipeline error:</strong> {pipelineError}
        </div>
      )}

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
