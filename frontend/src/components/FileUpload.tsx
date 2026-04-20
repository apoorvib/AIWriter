import { useRef, useState } from "react";
import { uploadSource } from "../api";
import type { SourceUploadResponse } from "../types";

interface Props {
  onUploaded: (source: SourceUploadResponse) => void;
}

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".markdown", ".notes"];

export default function FileUpload({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  async function handleFiles(files: FileList) {
    setError(null);
    for (const file of Array.from(files)) {
      const lowerName = file.name.toLowerCase();
      if (!ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext))) {
        setError("Supported files: PDF, DOCX, TXT, MD, Markdown, Notes.");
        continue;
      }
      setUploading(true);
      try {
        const result = await uploadSource(file);
        onUploaded(result);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed.");
      } finally {
        setUploading(false);
      }
    }
  }

  return (
    <div
      className={`file-upload-zone${dragOver ? " drag-over" : ""}`}
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
          <span className="upload-mark">SRC</span>
          <p>Drop source files here, or browse</p>
          <span className="upload-help">PDF, DOCX, TXT, MD, Markdown, Notes</span>
        </>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
