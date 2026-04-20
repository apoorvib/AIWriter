import { useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import FileUpload from "../components/FileUpload";
import { createJob, extractAssignment } from "../api";
import type { SourceUploadResponse } from "../types";

const ASSIGNMENT_ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.notes";

export default function NewJob() {
  const navigate = useNavigate();
  const assignmentInputRef = useRef<HTMLInputElement>(null);
  const [sources, setSources] = useState<SourceUploadResponse[]>([]);
  const [assignment, setAssignment] = useState("");
  const [assignmentMeta, setAssignmentMeta] = useState<string | null>(null);
  const [extractingAssignment, setExtractingAssignment] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleUploaded(source: SourceUploadResponse) {
    setSources((prev) => {
      if (prev.find((s) => s.source_id === source.source_id)) return prev;
      return [...prev, source];
    });
  }

  function removeSource(id: string) {
    setSources((prev) => prev.filter((s) => s.source_id !== id));
  }

  async function handleAssignmentFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setError(null);
    setExtractingAssignment(true);
    try {
      const result = await extractAssignment(file);
      setAssignment(result.text);
      setAssignmentMeta(`${file.name} - ${result.page_count} page(s), ${result.extraction_method}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to extract assignment text.");
    } finally {
      setExtractingAssignment(false);
      event.target.value = "";
    }
  }

  async function handleSubmit() {
    setError(null);
    if (!sources.length) {
      setError("Upload at least one source file.");
      return;
    }
    if (!assignment.trim()) {
      setError("Paste or extract your assignment text.");
      return;
    }

    setSubmitting(true);
    try {
      const job = await createJob(assignment, sources.map((s) => s.source_id));
      navigate(`/jobs/${job.job_id}/topics`, { state: { job } });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create job.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <p className="eyebrow">EssayWriter</p>
        <h1>Start a writing job</h1>
        <p className="subtitle">Add source material, capture the assignment, then choose a topic.</p>
      </header>

      <section className="section">
        <div className="section-heading">
          <span className="step-mark">1</span>
          <h2>Source files</h2>
        </div>
        <FileUpload onUploaded={handleUploaded} />
        {sources.length > 0 && (
          <div className="source-chips">
            {sources.map((s) => (
              <div key={s.source_id} className="source-chip-row">
                <span className="source-chip-name">{s.title}</span>
                <span className="source-chip-meta">
                  {s.source_type.toUpperCase()} - {s.page_count} pp - {s.chunk_count} chunks - {s.text_quality}
                </span>
                <button className="chip-remove" onClick={() => removeSource(s.source_id)} aria-label="Remove source">
                  Remove
                </button>
                {s.warnings.length > 0 && <span className="source-warning">{s.warnings.join(" ")}</span>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <div className="section-heading">
          <span className="step-mark">2</span>
          <h2>Assignment</h2>
        </div>
        <div className="assignment-actions">
          <button
            className="btn-secondary"
            type="button"
            onClick={() => assignmentInputRef.current?.click()}
            disabled={extractingAssignment}
          >
            {extractingAssignment ? "Extracting..." : "Extract from file"}
          </button>
          {assignmentMeta && <span className="assignment-meta">{assignmentMeta}</span>}
        </div>
        <input
          ref={assignmentInputRef}
          type="file"
          accept={ASSIGNMENT_ACCEPT}
          style={{ display: "none" }}
          onChange={handleAssignmentFile}
        />
        <textarea
          className="assignment-textarea"
          placeholder="Paste the full assignment prompt here."
          value={assignment}
          onChange={(e) => {
            setAssignment(e.target.value);
            setAssignmentMeta(null);
          }}
          rows={10}
        />
      </section>

      {error && <p className="error-text">{error}</p>}

      <button className="btn-primary" onClick={handleSubmit} disabled={submitting}>
        {submitting ? "Creating job..." : "Generate topic choices"}
      </button>
    </div>
  );
}
