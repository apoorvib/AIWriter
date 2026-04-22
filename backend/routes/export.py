from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import get_workflow, get_source_store, DATA_DIR
from backend.schemas import ExportResponse, SectionSourceEntry, ValidationSummary

router = APIRouter(prefix="/jobs", tags=["export"])


@router.get("/{job_id}/export", response_model=ExportResponse)
def get_export(job_id: str):
    workflow = get_workflow()
    try:
        job = workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.draft_id is None:
        raise HTTPException(status_code=404, detail="No draft available yet.")

    from essay_writer.drafting.storage import DraftStore
    from essay_writer.validation.storage import ValidationStore

    draft_store = DraftStore(DATA_DIR / "drafts")
    validation_store = ValidationStore(DATA_DIR / "validations")

    try:
        draft = draft_store.load_latest(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Draft not found.")

    try:
        validation = validation_store.load_latest(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Validation report not found.")

    return ExportResponse(
        job_id=job_id,
        draft_id=draft.id,
        content=draft.content,
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
        validation=ValidationSummary(
            passes=validation.passes,
            overall_quality=validation.llm_judgment.overall_quality,
            unsupported_claim_count=len(validation.llm_judgment.unsupported_claims),
            diagnostics=[
                {
                    "location": item.location,
                    "issue_type": item.issue_type,
                    "evidence": item.evidence,
                    "severity": item.severity,
                    "action": item.action,
                }
                for item in validation.llm_judgment.diagnostics
            ],
            revision_suggestions=validation.llm_judgment.revision_suggestions,
        ),
    )
