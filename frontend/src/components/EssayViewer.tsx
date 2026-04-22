import type { ExportResponse } from "../types";
import { useEffect, useMemo } from "react";

interface Props {
  data: ExportResponse;
}

export default function EssayViewer({ data }: Props) {
  const { validation } = data;
  const qualityPct = Math.round(validation.overall_quality * 100);
  const downloadUrl = useMemo(
    () => URL.createObjectURL(new Blob([data.content], { type: "text/markdown;charset=utf-8" })),
    [data.content]
  );

  useEffect(() => () => URL.revokeObjectURL(downloadUrl), [downloadUrl]);

  return (
    <div className="essay-viewer">
      <div className={`validation-badge ${validation.passes ? "pass" : "fail"}`}>
        {validation.passes ? "Validation passed" : "Validation failed"} - quality {qualityPct}%
      </div>

      <a className="btn-secondary download-link" href={downloadUrl} download={`${data.job_id}.md`}>
        Download Markdown
      </a>

      {!validation.passes && validation.diagnostics.length > 0 && (
        <div className="revision-box">
          <strong>Validation diagnostics:</strong>
          <ul>
            {validation.diagnostics.map((d, i) => (
              <li key={i}>
                {d.location}: {d.issue_type} ({d.severity}) - {d.evidence}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!validation.passes && validation.revision_suggestions.length > 0 && (
        <div className="revision-box">
          <strong>Legacy revision suggestions:</strong>
          <ul>
            {validation.revision_suggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="essay-content">
        {data.content.split("\n").map((line, i) => (
          <p key={i} className={line === "" ? "essay-para-break" : "essay-para"}>
            {line}
          </p>
        ))}
      </div>

      {data.bibliography_candidates.length > 0 && (
        <div className="bibliography">
          <h3>Bibliography Candidates</h3>
          <ol>
            {data.bibliography_candidates.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ol>
        </div>
      )}

      {data.section_source_map.length > 0 && (
        <details className="source-map-details">
          <summary>Source map ({data.section_source_map.length} sections)</summary>
          <table className="source-map-table">
            <thead>
              <tr>
                <th>Section</th>
                <th>Sources</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {data.section_source_map.map((s) => (
                <tr key={s.section_id}>
                  <td>{s.heading || s.section_id}</td>
                  <td>{s.source_ids.join(", ") || "-"}</td>
                  <td>{s.note_ids.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
