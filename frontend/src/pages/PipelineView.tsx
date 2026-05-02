import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import StageTracker from "../components/StageTracker";
import EssayViewer from "../components/EssayViewer";
import {
  createManualRevisionRun,
  getDraft,
  getExport,
  getExportById,
  getJob,
  getManualRevisionRun,
  listDrafts,
  listExports,
  listManualRevisionRuns,
  openJobEvents,
  runPipeline,
  saveUserEdit,
} from "../api";
import type {
  AntiAiSummary,
  DraftResponse,
  DraftSummary,
  ExportResponse,
  ExportSummary,
  ManualLens,
  ManualMode,
  ManualRevisionRunResponse,
  ManualRevisionRunSummary,
  PipelineStage,
  SSEEvent,
  ToneAlignmentSummary,
  ValidationSummary,
} from "../types";

const INITIAL_STAGES: PipelineStage[] = [
  { key: "research_planning", label: "Plan", status: "pending" },
  { key: "research", label: "Research", status: "pending" },
  { key: "outlining", label: "Outline", status: "pending" },
  { key: "drafting", label: "Draft", status: "pending" },
  { key: "validation", label: "Validate", status: "pending" },
  { key: "tone_alignment", label: "Tone", status: "pending" },
  { key: "revision", label: "Revise", status: "pending" },
  { key: "export", label: "Export", status: "pending" },
];

const STAGE_LABELS: Record<string, string> = {
  research_planning: "Research Planning",
  research: "Research",
  outlining: "Outlining",
  drafting: "Drafting",
  validation: "Validation",
  tone_alignment: "Tone Alignment",
  revision: "Revision",
  export: "Export",
  workflow: "Workflow",
  starting: "Pipeline startup",
};

const LENS_OPTIONS: Array<{ key: ManualLens; label: string }> = [
  { key: "evidence", label: "Evidence" },
  { key: "citations", label: "Citations" },
  { key: "assignment_fit", label: "Assignment fit" },
  { key: "length", label: "Length" },
  { key: "tone", label: "Tone" },
  { key: "anti_ai", label: "Anti-AI" },
];

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
        <span className="pipeline-error-icon">X</span>
        <span className="pipeline-error-title">
          {stageLabel ? `Failed during ${stageLabel}` : "Pipeline failed"}
        </span>
        {err.errorType && <code className="pipeline-error-type">{err.errorType}</code>}
      </div>
      <p className="pipeline-error-message">{err.message}</p>
      {err.detail && err.detail !== err.message && (
        <div className="pipeline-error-detail-toggle">
          <button className="text-button" onClick={() => setShowDetail((v) => !v)}>
            {showDetail ? "Hide technical detail" : "Show technical detail"}
          </button>
          {showDetail && <pre className="pipeline-error-detail">{err.detail}</pre>}
        </div>
      )}
    </div>
  );
}

function ValidationSummaryPanel({ title, data }: { title: string; data: ValidationSummary | null }) {
  if (!data) return null;
  return (
    <div className="artifact-result-card">
      <h4>{title}</h4>
      <p className="artifact-meta-line">
        {data.passes ? "Passes" : "Needs work"} - quality {Math.round(data.overall_quality * 100)}%
      </p>
      {data.diagnostics.length > 0 && (
        <ul className="artifact-list-compact">
          {data.diagnostics.slice(0, 6).map((item, index) => (
            <li key={`${item.location}-${index}`}>
              {item.location}: {item.issue_type} ({item.severity}) - {item.evidence}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ToneSummaryPanel({ title, data }: { title: string; data: ToneAlignmentSummary | null }) {
  if (!data) return null;
  return (
    <div className="artifact-result-card">
      <h4>{title}</h4>
      <p className="artifact-meta-line">
        Alignment {Math.round(data.overall_alignment * 100)}% {data.requires_revision ? "- revision suggested" : "- acceptable"}
      </p>
      {data.revision_targets.length > 0 && (
        <ul className="artifact-list-compact">
          {data.revision_targets.slice(0, 6).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AntiAiSummaryPanel({ title, data }: { title: string; data: AntiAiSummary | null }) {
  if (!data) return null;
  return (
    <div className="artifact-result-card">
      <h4>{title}</h4>
      <p className="artifact-meta-line">
        Em dashes {data.em_dash_count}, tier-1 vocab hits {data.tier1_vocab_hits.length}, signposting hits {data.signposting_hits.length}
      </p>
      <ul className="artifact-list-compact">
        <li>Mechanical burstiness: {data.mechanical_burstiness_count}</li>
        <li>Contrastive negation: {data.contrastive_negation_count}</li>
        <li>Concrete engagement present: {data.concrete_engagement_present ? "yes" : "no"}</li>
      </ul>
    </div>
  );
}

export default function PipelineView() {
  const { jobId } = useParams<{ jobId: string }>();
  const [stages, setStages] = useState<PipelineStage[]>(INITIAL_STAGES);
  const [essay, setEssay] = useState<ExportResponse | null>(null);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [exports, setExports] = useState<ExportSummary[]>([]);
  const [manualRuns, setManualRuns] = useState<ManualRevisionRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<ManualRevisionRunResponse | null>(null);
  const [pipelineError, setPipelineError] = useState<PipelineError | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
  const [progressMsg, setProgressMsg] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [externalSearchAllowed, setExternalSearchAllowed] = useState(false);
  const [loadingArtifacts, setLoadingArtifacts] = useState(true);
  const [editorText, setEditorText] = useState("");
  const [editorSavedText, setEditorSavedText] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const [editorCurrentDraftId, setEditorCurrentDraftId] = useState<string | null>(null);
  const [editorCurrentDraftVersion, setEditorCurrentDraftVersion] = useState<number | null>(null);
  const [editorBaseExportId, setEditorBaseExportId] = useState<string | null>(null);
  const [editorLabel, setEditorLabel] = useState<string>("No draft loaded");
  const [saveBusy, setSaveBusy] = useState(false);
  const [runBusy, setRunBusy] = useState<ManualMode | null>(null);
  const [instruction, setInstruction] = useState("");
  const [selectedLenses, setSelectedLenses] = useState<ManualLens[]>(["tone", "anti_ai"]);
  const esRef = useRef<EventSource | null>(null);
  const editorInitializedRef = useRef(false);

  function updateStage(key: string, status: PipelineStage["status"]) {
    setStages((prev) => prev.map((s) => (s.key === key ? { ...s, status } : s)));
  }

  function loadDraftIntoEditor(draft: DraftResponse) {
    setEditorText(draft.content);
    setEditorSavedText(draft.content);
    setEditorDirty(false);
    setEditorCurrentDraftId(draft.draft_id);
    setEditorCurrentDraftVersion(draft.version);
    setEditorBaseExportId(null);
    setEditorLabel(`Draft v${draft.version} - ${draftOriginLabel(draft.origin)}`);
  }

  function loadExportIntoEditor(data: ExportResponse) {
    setEditorText(data.draft_content);
    setEditorSavedText(data.draft_content);
    setEditorDirty(false);
    setEditorCurrentDraftId(data.draft_id);
    setEditorCurrentDraftVersion(data.draft_version);
    setEditorBaseExportId(data.export_id);
    setEditorLabel(`Export ${data.export_id} -> draft v${data.draft_version ?? "?"}`);
  }

  async function refreshArtifacts() {
    if (!jobId) return;
    setLoadingArtifacts(true);
    try {
      const [job, draftList, exportList, runList] = await Promise.all([
        getJob(jobId),
        listDrafts(jobId),
        listExports(jobId),
        listManualRevisionRuns(jobId),
      ]);
      setDrafts(draftList);
      setExports(exportList);
      setManualRuns(runList);

      const targetExportId = job.final_export_id ?? exportList[exportList.length - 1]?.export_id ?? null;
      if (targetExportId && (!essay || essay.export_id !== targetExportId)) {
        setEssay(await getExportById(jobId, targetExportId));
      } else if (!targetExportId) {
        setEssay(null);
      }

      if (!editorInitializedRef.current && draftList.length > 0) {
        const latestDraft = await getDraft(jobId, draftList[draftList.length - 1].version);
        loadDraftIntoEditor(latestDraft);
        editorInitializedRef.current = true;
      }
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to load saved artifacts.");
    } finally {
      setLoadingArtifacts(false);
    }
  }

  useEffect(() => () => esRef.current?.close(), []);
  useEffect(() => {
    editorInitializedRef.current = false;
    setEssay(null);
    setDrafts([]);
    setExports([]);
    setManualRuns([]);
    setSelectedRun(null);
    setEditorText("");
    setEditorSavedText("");
    setEditorDirty(false);
    setEditorCurrentDraftId(null);
    setEditorCurrentDraftVersion(null);
    setEditorBaseExportId(null);
    setEditorLabel("No draft loaded");
    refreshArtifacts();
  }, [jobId]);

  async function handleStart() {
    if (!jobId || started) return;
    setStarted(true);
    setPipelineError(null);
    setManualError(null);

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
          setStarted(false);
          if (payload.passes) {
            setStages((prev) =>
              prev.map((stage) =>
                (stage.key === "revision" || stage.key === "tone_alignment") && stage.status === "pending"
                  ? { ...stage, status: "skipped" }
                  : stage
              )
            );
          }
          if (payload.final_export_id) {
            try {
              setEssay(await getExport(jobId));
            } catch {
              setPipelineError({
                message: "Pipeline finished but the export could not be loaded.",
                detail: null,
                stage: "export",
                errorType: null,
              });
            }
          } else if (!payload.passes) {
            setPipelineError({
              message: "This pipeline pass finished, but another revision is still required. Start the pipeline again to continue.",
              detail: null,
              stage: "revision",
              errorType: null,
            });
          }
          await refreshArtifacts();
        } else if (payload.event === "error") {
          setProgressMsg(null);
          setStarted(false);
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
        setStarted(false);
        setPipelineError({
          message: "Lost connection to pipeline events. The pipeline may still be running - refresh to check.",
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

  async function handleOpenDraft(version: number) {
    if (!jobId) return;
    setManualError(null);
    try {
      loadDraftIntoEditor(await getDraft(jobId, version));
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to load draft.");
    }
  }

  async function handleViewExport(exportId: string) {
    if (!jobId) return;
    setManualError(null);
    try {
      setEssay(await getExportById(jobId, exportId));
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to load export.");
    }
  }

  async function handleEditFromExport(exportId: string) {
    if (!jobId) return;
    setManualError(null);
    try {
      loadExportIntoEditor(await getExportById(jobId, exportId));
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to load export for editing.");
    }
  }

  async function persistEditor(): Promise<DraftResponse | null> {
    if (!jobId) return null;
    if (!editorDirty) {
      if (editorCurrentDraftVersion != null) {
        return getDraft(jobId, editorCurrentDraftVersion);
      }
      return null;
    }
    if (!editorText.trim()) {
      throw new Error("Draft text is empty.");
    }
    if (!editorCurrentDraftId && !editorBaseExportId) {
      throw new Error("Open an existing draft or export before saving edits.");
    }
    const saved = await saveUserEdit(jobId, {
      content: editorText,
      baseDraftId: editorBaseExportId ? null : editorCurrentDraftId,
      baseExportId: editorBaseExportId,
    });
    loadDraftIntoEditor(saved);
    await refreshArtifacts();
    return saved;
  }

  async function handleSaveEdit() {
    setSaveBusy(true);
    setManualError(null);
    try {
      await persistEditor();
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to save edited draft.");
    } finally {
      setSaveBusy(false);
    }
  }

  async function handleManualRun(mode: ManualMode) {
    if (!jobId) return;
    setRunBusy(mode);
    setManualError(null);
    try {
      const saved = await persistEditor();
      const sourceDraftId = saved?.draft_id ?? editorCurrentDraftId;
      if (!sourceDraftId) {
        throw new Error("Load or save a draft before running manual review.");
      }
      const run = await createManualRevisionRun(jobId, {
        sourceDraftId,
        mode,
        instruction,
        selectedLenses,
      });
      setSelectedRun(run);
      await refreshArtifacts();
      if (run.result_draft_version != null) {
        loadDraftIntoEditor(await getDraft(jobId, run.result_draft_version));
      }
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to run manual reiteration.");
    } finally {
      setRunBusy(null);
    }
  }

  async function handleOpenRun(runId: string) {
    if (!jobId) return;
    setManualError(null);
    try {
      setSelectedRun(await getManualRevisionRun(jobId, runId));
    } catch (e) {
      setManualError(e instanceof Error ? e.message : "Failed to load the saved review run.");
    }
  }

  function toggleLens(lens: ManualLens) {
    setSelectedLenses((prev) =>
      prev.includes(lens) ? prev.filter((item) => item !== lens) : [...prev, lens]
    );
  }

  return (
    <div className="page page-wide">
      <header className="page-header">
        <p className="eyebrow">Job {jobId}</p>
        <h1>Run and iterate on the essay</h1>
        <p className="subtitle">Run the pipeline, inspect saved drafts and exports, then save your own edits and launch focused review or revise passes.</p>
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

      {progressMsg && <p className="progress-msg">{progressMsg}</p>}
      {pipelineError && <PipelineErrorPanel err={pipelineError} />}
      {manualError && <p className="error-text">{manualError}</p>}
      {loadingArtifacts && <p className="running-hint">Loading saved drafts, exports, and review runs...</p>}

      {essay && (
        <div className="essay-section">
          <div className="artifact-header">
            <div>
              <h2>Latest export</h2>
              <p className="artifact-meta-line">Export {essay.export_id} from draft v{essay.draft_version ?? "?"}</p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => handleEditFromExport(essay.export_id)}>
              Edit from export
            </button>
          </div>
          <EssayViewer data={essay} />
        </div>
      )}

      <section className="artifact-grid">
        <div className="artifact-panel">
          <div className="artifact-header">
            <h2>Draft history</h2>
            <span className="artifact-count">{drafts.length}</span>
          </div>
          {drafts.length === 0 ? (
            <p className="running-hint">No saved drafts yet.</p>
          ) : (
            <div className="artifact-list">
              {drafts
                .slice()
                .sort((a, b) => b.version - a.version)
                .map((draft) => (
                  <div key={draft.draft_id} className="artifact-row">
                    <div className="artifact-copy">
                      <strong>Draft v{draft.version}</strong>
                      <p className="artifact-meta-line">{draftOriginLabel(draft.origin)} • {draft.created_by}</p>
                      <p className="artifact-preview">{draft.preview}</p>
                    </div>
                    <button className="btn-secondary" type="button" onClick={() => handleOpenDraft(draft.version)}>
                      Open
                    </button>
                  </div>
                ))}
            </div>
          )}
        </div>

        <div className="artifact-panel">
          <div className="artifact-header">
            <h2>Export history</h2>
            <span className="artifact-count">{exports.length}</span>
          </div>
          {exports.length === 0 ? (
            <p className="running-hint">No exports yet.</p>
          ) : (
            <div className="artifact-list">
              {exports
                .slice()
                .reverse()
                .map((item) => (
                  <div key={item.export_id} className="artifact-row">
                    <div className="artifact-copy">
                      <strong>{item.export_id}</strong>
                      <p className="artifact-meta-line">Draft v{item.draft_version ?? "?"}</p>
                      <p className="artifact-preview">{item.preview}</p>
                    </div>
                    <div className="artifact-actions">
                      <button className="btn-secondary" type="button" onClick={() => handleViewExport(item.export_id)}>
                        View
                      </button>
                      <button className="btn-secondary" type="button" onClick={() => handleEditFromExport(item.export_id)}>
                        Edit
                      </button>
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      </section>

      <section className="editor-panel">
        <div className="artifact-header">
          <div>
            <h2>Draft editor</h2>
            <p className="artifact-meta-line">{editorLabel}</p>
          </div>
          <button className="btn-secondary" type="button" onClick={handleSaveEdit} disabled={saveBusy || !editorDirty}>
            {saveBusy ? "Saving..." : editorDirty ? "Save user edit" : "Saved"}
          </button>
        </div>
        <textarea
          className="assignment-textarea editor-textarea"
          value={editorText}
          onChange={(e) => {
            setEditorText(e.target.value);
            setEditorDirty(e.target.value !== editorSavedText);
          }}
          placeholder="Open a draft or export, then edit it here."
        />
      </section>

      <section className="manual-panel">
        <div className="artifact-header">
          <div>
            <h2>Manual reiteration</h2>
            <p className="artifact-meta-line">Save the current editor text first if you want the run to branch from your latest changes.</p>
          </div>
        </div>

        <input
          className="instruction-input"
          placeholder="Optional instruction, e.g. keep my new paragraph 4, tighten the intro, and re-check citations."
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
        />

        <div className="lens-grid">
          {LENS_OPTIONS.map((option) => (
            <label key={option.key} className="lens-chip">
              <input
                type="checkbox"
                checked={selectedLenses.includes(option.key)}
                onChange={() => toggleLens(option.key)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>

        <div className="button-row">
          <button
            className="btn-secondary"
            type="button"
            disabled={runBusy !== null || selectedLenses.length === 0}
            onClick={() => handleManualRun("review_only")}
          >
            {runBusy === "review_only" ? "Reviewing..." : "Review only"}
          </button>
          <button
            className="btn-primary"
            type="button"
            disabled={runBusy !== null || selectedLenses.length === 0}
            onClick={() => handleManualRun("revise")}
          >
            {runBusy === "revise" ? "Revising..." : "Review and revise"}
          </button>
        </div>
      </section>

      <section className="artifact-grid">
        <div className="artifact-panel">
          <div className="artifact-header">
            <h2>Saved review runs</h2>
            <span className="artifact-count">{manualRuns.length}</span>
          </div>
          {manualRuns.length === 0 ? (
            <p className="running-hint">No saved review runs yet.</p>
          ) : (
            <div className="artifact-list">
              {manualRuns
                .slice()
                .reverse()
                .map((run) => (
                  <div key={run.run_id} className="artifact-row">
                    <div className="artifact-copy">
                      <strong>{run.mode === "revise" ? "Review + revise" : "Review only"}</strong>
                      <p className="artifact-meta-line">
                        Source v{run.source_draft_version ?? "?"}
                        {run.result_draft_version != null ? ` -> result v${run.result_draft_version}` : ""}
                      </p>
                      <p className="artifact-preview">{run.selected_lenses.join(", ")}</p>
                    </div>
                    <button className="btn-secondary" type="button" onClick={() => handleOpenRun(run.run_id)}>
                      Open
                    </button>
                  </div>
                ))}
            </div>
          )}
        </div>

        <div className="artifact-panel">
          <div className="artifact-header">
            <h2>Run detail</h2>
            {selectedRun?.result_draft_version != null && (
              <button
                className="btn-secondary"
                type="button"
                onClick={() => handleOpenDraft(selectedRun.result_draft_version!)}
              >
                Open result draft
              </button>
            )}
          </div>
          {!selectedRun ? (
            <p className="running-hint">Open a saved review run to inspect the stored outputs.</p>
          ) : (
            <div className="artifact-result-stack">
              <div className="artifact-result-card">
                <h4>Request</h4>
                <p className="artifact-meta-line">
                  {selectedRun.mode === "revise" ? "Review + revise" : "Review only"} • {selectedRun.selected_lenses.join(", ")}
                </p>
                {selectedRun.instruction && <p className="artifact-preview">{selectedRun.instruction}</p>}
                {selectedRun.change_summary.length > 0 && (
                  <ul className="artifact-list-compact">
                    {selectedRun.change_summary.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
                {selectedRun.warnings.length > 0 && (
                  <ul className="artifact-list-compact warning-list">
                    {selectedRun.warnings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>

              <ValidationSummaryPanel title="Pre-revision validation" data={selectedRun.pre_revision_validation} />
              <ToneSummaryPanel title="Pre-revision tone alignment" data={selectedRun.pre_revision_tone_alignment} />
              <AntiAiSummaryPanel title="Pre-revision anti-AI" data={selectedRun.pre_revision_anti_ai} />

              <ValidationSummaryPanel title="Post-revision validation" data={selectedRun.post_revision_validation} />
              <ToneSummaryPanel title="Post-revision tone alignment" data={selectedRun.post_revision_tone_alignment} />
              <AntiAiSummaryPanel title="Post-revision anti-AI" data={selectedRun.post_revision_anti_ai} />
            </div>
          )}
        </div>
      </section>

      {started && !essay && !pipelineError && (
        <p className="running-hint">The pipeline is running. Long source sets can take a few minutes.</p>
      )}
    </div>
  );
}

function draftOriginLabel(origin: string) {
  return (
    {
      generated: "Generated",
      style_revision: "Style pass",
      system_revision: "System revision",
      user_edit: "Your edit",
      manual_llm_revision: "AI revision from your edit",
    }[origin] ?? origin
  );
}
