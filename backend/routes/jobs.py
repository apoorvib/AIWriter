from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import get_task_spec_parser, get_task_spec_store, get_workflow
from backend.schemas import CreateJobRequest, CreateJobResponse, JobStatusResponse

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

    workflow = get_workflow()
    job = workflow.create_job(
        task_spec_id=task_spec.id,
        source_ids=req.source_ids,
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
        error=error_msg,
    )
