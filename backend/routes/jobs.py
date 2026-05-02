from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import (
    DATA_DIR,
    get_task_spec_parser,
    get_task_spec_store,
    get_workflow,
    get_writing_style_content_service,
    get_writing_style_content_store,
    get_writing_style_ingestion_service,
    get_writing_style_sample_store,
)
from backend.schemas import CreateJobRequest, CreateJobResponse, JobStatusResponse
from backend.writing_style_support import resolve_writing_style_payload, sync_existing_human_samples

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=CreateJobResponse)
def create_job(req: CreateJobRequest):
    if not req.assignment_text.strip():
        raise HTTPException(status_code=400, detail="assignment_text is required.")
    if not req.source_ids:
        raise HTTPException(status_code=400, detail="At least one source_id is required.")

    parser = get_task_spec_parser()
    task_spec = parser.parse(
        req.assignment_text,
        source_document_ids=req.source_ids,
    )

    writing_style_payload = None
    if req.writing_style_sample_ids:
        sample_store = get_writing_style_sample_store()
        sync_existing_human_samples(
            sample_store,
            get_writing_style_ingestion_service(),
            DATA_DIR / "human_samples",
        )
        try:
            writing_style_payload = resolve_writing_style_payload(
                req.writing_style_sample_ids,
                sample_store=sample_store,
                content_store=get_writing_style_content_store(),
                content_service=get_writing_style_content_service(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown writing_style_sample_id: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    workflow = get_workflow()
    job = workflow.create_job(
        task_spec_id=task_spec.id,
        source_ids=req.source_ids,
    )
    if writing_style_payload is not None:
        job = workflow.attach_writing_style(
            job_id=job.id,
            sample_ids=[sample.sample_id for sample in writing_style_payload.samples],
            content_id=writing_style_payload.style_content.id,
        )

    get_task_spec_store().save(task_spec)

    return CreateJobResponse(
        job_id=job.id,
        task_spec_id=task_spec.id,
        blocking_questions=list(task_spec.blocking_questions),
        warnings=list(task_spec.nonblocking_warnings),
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    workflow = get_workflow()
    try:
        job = workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")

    error_msg = job.error_state.message if job.error_state else None
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        current_stage=job.current_stage,
        selected_topic_id=job.selected_topic_id,
        draft_id=job.draft_id,
        final_export_id=job.final_export_id,
        writing_style_sample_ids=job.writing_style_sample_ids,
        error=error_msg,
    )
