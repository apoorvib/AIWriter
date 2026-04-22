from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from backend.deps import get_workflow, get_workflow_runner
from backend.schemas import RunPipelineRequest, RunPipelineResponse

router = APIRouter(prefix="/jobs", tags=["pipeline"])
logger = logging.getLogger("essay_writer.api")

_job_queues: dict[str, asyncio.Queue] = {}
_executor = ThreadPoolExecutor(max_workers=4)


def _get_or_create_queue(job_id: str) -> asyncio.Queue:
    if job_id not in _job_queues:
        _job_queues[job_id] = asyncio.Queue()
    return _job_queues[job_id]


def _run_pipeline_sync(
    job_id: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    external_search_allowed: bool,
) -> None:
    """Run the persisted workflow in a worker thread and push SSE updates."""

    def emit(event: str, **kwargs: Any) -> None:
        payload = {"event": event, **kwargs}
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    current_stage: list[str] = ["starting"]

    def on_stage(stage: str, status: str) -> None:
        if status == "start":
            current_stage[0] = stage
        emit(f"stage_{status}", stage=stage)

    def on_progress(message: str) -> None:
        emit("progress", message=message)

    try:
        runner = get_workflow_runner()
        result = runner.run_selected_job(
            job_id,
            external_search_allowed=external_search_allowed,
            on_stage=on_stage,
            on_progress=on_progress,
        )
        if not result.validation.passes and result.job.current_stage == "revision":
            result = runner.run_selected_job(job_id, on_stage=on_stage, on_progress=on_progress)

        emit(
            "complete",
            passes=result.validation.passes,
            draft_id=result.draft.id,
            final_export_id=result.final_export.id if result.final_export else None,
        )
    except Exception as exc:
        logger.exception("Pipeline error for job %s at stage %s", job_id, current_stage[0])
        emit(
            "error",
            message=_user_facing_message(exc),
            detail=str(exc),
            stage=current_stage[0],
            error_type=type(exc).__name__,
        )


@router.post("/{job_id}/run", response_model=RunPipelineResponse)
async def run_pipeline(job_id: str, req: RunPipelineRequest | None = None):
    workflow = get_workflow()
    try:
        job = workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.selected_topic_id is None:
        raise HTTPException(status_code=400, detail="No topic selected yet.")
    if job.status not in {"research_planning_ready", "drafting_ready", "validation_ready", "validation_complete"}:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not ready to run (status={job.status}).",
        )

    queue = _get_or_create_queue(job_id)
    loop = asyncio.get_event_loop()
    external_search_allowed = req.external_search_allowed if req else False
    loop.run_in_executor(_executor, _run_pipeline_sync, job_id, queue, loop, external_search_allowed)

    return RunPipelineResponse(job_id=job_id, status="started")


@router.get("/{job_id}/events")
async def job_events(job_id: str):
    queue = _get_or_create_queue(job_id)

    async def event_generator():
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield {"data": json.dumps(payload)}
                event = payload.get("event")
                if event in ("complete", "error"):
                    _job_queues.pop(job_id, None)
                    break
            except asyncio.TimeoutError:
                yield {"data": json.dumps({"event": "ping"})}

    return EventSourceResponse(event_generator())


def _user_facing_message(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "InsufficientEvidenceError":
        return "The selected topic doesn't have enough source coverage to draft safely. Go back and choose a different topic or add more source files."
    if name == "WorkflowNotRunnableError":
        return f"Job cannot be run in its current state: {exc}"
    if name == "WorkflowContractError":
        return f"Internal workflow state error — this is likely a bug. Detail: {exc}"
    if name in ("LLMError", "LLMConfigurationError"):
        return f"AI model error: {exc}"
    if name == "APIStatusError":
        return f"AI API returned an error (check your API key and usage limits): {exc}"
    if name == "APIConnectionError":
        return "Could not reach the AI API. Check your network connection and try again."
    if name == "RateLimitError":
        return "AI API rate limit reached. Wait a moment and try again."
    if name == "AuthenticationError":
        return "AI API authentication failed. Check your API key in Settings or environment variables."
    return str(exc)
