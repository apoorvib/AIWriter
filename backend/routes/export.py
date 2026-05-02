from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import get_draft_store, get_export_store, get_validation_store, get_workflow
from backend.schemas import ExportResponse, ExportSummaryResponse, SectionSourceEntry, ValidationSummary, ValidationDiagnosticResponse
from essay_writer.validation.schema import ValidationReport

router = APIRouter(prefix="/jobs", tags=["export"])


@router.get("/{job_id}/export", response_model=ExportResponse)
def get_latest_export(job_id: str):
    workflow = get_workflow()
    try:
        job = workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.final_export_id is None:
        raise HTTPException(status_code=404, detail="No final export available yet.")
    return _load_export_response(job_id, job.final_export_id)


@router.get("/{job_id}/exports", response_model=list[ExportSummaryResponse])
def list_exports(job_id: str):
    workflow = get_workflow()
    try:
        workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")

    draft_store = get_draft_store()
    exports = get_export_store().list_versions(job_id)
    summaries: list[ExportSummaryResponse] = []
    for export in exports:
        try:
            draft = draft_store.find_by_id(job_id, export.draft_id)
            draft_version = draft.version
            preview = _preview(draft.content)
        except KeyError:
            draft_version = None
            preview = _preview(export.content)
        summaries.append(
            ExportSummaryResponse(
                export_id=export.id,
                draft_id=export.draft_id,
                draft_version=draft_version,
                created_at=export.created_at,
                preview=preview,
            )
        )
    return summaries


@router.get("/{job_id}/exports/{export_id}", response_model=ExportResponse)
def get_export(job_id: str, export_id: str):
    workflow = get_workflow()
    try:
        workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")
    return _load_export_response(job_id, export_id)


def _load_export_response(job_id: str, export_id: str) -> ExportResponse:
    export_store = get_export_store()
    draft_store = get_draft_store()
    validation_store = get_validation_store()
    try:
        export = export_store.load(job_id, export_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Export not found.")
    try:
        draft = draft_store.find_by_id(job_id, export.draft_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Linked draft not found for export.")
    try:
        validation = validation_store.load(job_id, _report_version(export.validation_report_id))
    except (FileNotFoundError, KeyError, ValueError):
        raise HTTPException(status_code=404, detail="Validation report not found for export.")

    return ExportResponse(
        job_id=job_id,
        export_id=export.id,
        draft_id=draft.id,
        draft_version=draft.version,
        content=export.content,
        draft_content=draft.content,
        section_source_map=[
            SectionSourceEntry(
                section_id=s.section_id,
                heading=s.heading,
                note_ids=s.note_ids,
                source_ids=s.source_ids,
            )
            for s in draft.section_source_map
        ],
        bibliography_candidates=draft.bibliography_candidates,
        validation=_validation_summary(validation),
    )


def _validation_summary(validation: ValidationReport) -> ValidationSummary:
    return ValidationSummary(
        passes=validation.passes,
        overall_quality=validation.llm_judgment.overall_quality,
        unsupported_claim_count=len(validation.llm_judgment.unsupported_claims),
        diagnostics=[
            ValidationDiagnosticResponse(
                location=item.location,
                issue_type=item.issue_type,
                evidence=item.evidence,
                severity=item.severity,
                action=item.action,
            )
            for item in validation.llm_judgment.diagnostics
        ],
        revision_suggestions=validation.llm_judgment.revision_suggestions,
    )


def _report_version(report_id: str) -> int:
    version_text = report_id.rsplit(":v", 1)[-1]
    if not version_text.isdigit():
        raise ValueError(f"Invalid report version reference: {report_id}")
    return int(version_text)


def _preview(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
