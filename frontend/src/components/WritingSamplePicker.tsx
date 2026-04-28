import { useRef, useState } from "react";
import { uploadWritingSample } from "../api";
import type { WritingSample } from "../types";

interface Props {
  samples: WritingSample[];
  selectedIds: string[];
  loading: boolean;
  loadError: string | null;
  onToggle: (sampleId: string) => void;
  onUploaded: (sample: WritingSample) => void;
}

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".markdown", ".notes"];

export default function WritingSamplePicker({
  samples,
  selectedIds,
  loading,
  loadError,
  onToggle,
  onUploaded,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  async function handleFiles(files: FileList) {
    setUploadError(null);
    for (const file of Array.from(files)) {
      const lowerName = file.name.toLowerCase();
      if (!ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext))) {
        setUploadError("Supported files: PDF, DOCX, TXT, MD, Markdown, Notes.");
        continue;
      }
      setUploading(true);
      try {
        const result = await uploadWritingSample(file);
        onUploaded(result);
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : "Upload failed.");
      } finally {
        setUploading(false);
      }
    }
  }

  return (
    <div className="writing-style-panel">
      <div
        className={`file-upload-zone writing-style-upload${dragOver ? " drag-over": ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          multiple
          style={{ display: "none" }}
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
        {uploading ? (
          <span className="spinner">Uploading...</span>
        ) : (
          <>
            <span className="upload-mark">STYLE</span>
            <p>Drop writing samples here, or browse</p>
            <span className="upload-help">Used only for tone and style matching</span>
          </>
        )}
      </div>

      {loadError && <p className="error-text">{loadError}</p>}
      {uploadError && <p className="error-text">{uploadError}</p>}

      {loading ? (
        <p className="running-hint">Loading saved writing samples...</p>
      ) : samples.length > 0 ? (
        <div className="writing-sample-list">
          {samples.map((sample) => {
            const checked = selectedIds.includes(sample.sample_id);
            return (
              <label
                key={sample.sample_id}
                className={`writing-sample-row${checked ? " selected" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(sample.sample_id)}
                />
                <div className="writing-sample-copy">
                  <span className="source-chip-name">{sample.title}</span>
                  <span className="source-chip-meta">
                    {sample.source_type.toUpperCase()} - {sample.word_count} words - {sample.page_count} page(s)
                  </span>
                  <span className="writing-sample-file">{sample.source_filename}</span>
                  {sample.warnings.length > 0 && (
                    <span className="source-warning">{sample.warnings.join(" ")}</span>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      ) : (
        <p className="running-hint">
          No writing samples uploaded yet. You can continue without them.
        </p>
      )}
    </div>
  );
}
