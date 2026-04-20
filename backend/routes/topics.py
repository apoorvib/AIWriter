from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import (
    get_workflow,
    get_topic_ideation_service,
    get_source_store,
    get_task_spec_store,
)
from backend.schemas import (
    CandidateTopicResponse,
    TopicSourceLead,
    TopicsGenerateRequest,
    TopicsGenerateResponse,
    TopicSelectRequest,
    TopicSelectResponse,
    TopicRejectRequest,
    TopicRejectResponse,
)

router = APIRouter(prefix="/jobs", tags=["topics"])


@router.post("/{job_id}/topics/generate", response_model=TopicsGenerateResponse)
def generate_topics(job_id: str, req: TopicsGenerateRequest = TopicsGenerateRequest()):
    workflow = get_workflow()
    try:
        job = workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.task_spec_id is None:
        raise HTTPException(status_code=400, detail="Job has no task spec.")

    task_spec = get_task_spec_store().load_latest(job.task_spec_id)

    source_store = get_source_store()
    source_cards = [source_store.load_source_card(sid) for sid in job.source_ids]
    index_manifests = []
    source_maps = []
    for sid in job.source_ids:
        try:
            index_manifests.append(source_store.load_index_manifest(sid))
        except (FileNotFoundError, KeyError):
            pass
        try:
            source_maps.append(source_store.load_source_map(sid))
        except (FileNotFoundError, KeyError):
            pass

    previous_candidates = workflow.get_previous_candidates(job_id)
    rejected_topics = workflow.get_rejected_topics(job_id)

    service = get_topic_ideation_service()
    result = service.generate(
        task_spec,
        source_cards=source_cards,
        index_manifests=index_manifests,
        source_maps=source_maps,
        previous_candidates=previous_candidates or None,
        rejected_topics=rejected_topics or None,
        user_instruction=req.user_instruction,
    )

    round_ = workflow.record_topic_round(
        job_id=job_id,
        topic_result=result,
        user_instruction=req.user_instruction,
        previous_candidates=previous_candidates or None,
    )

    candidates = [
        CandidateTopicResponse(
            topic_id=c.id,
            title=c.title,
            research_question=c.research_question,
            tentative_thesis_direction=c.tentative_thesis_direction,
            rationale=c.rationale,
            fit_score=c.fit_score,
            evidence_score=c.evidence_score,
            originality_score=c.originality_score,
            source_leads=[
                TopicSourceLead(source_id=lead.source_id, chunk_count=len(lead.chunk_ids))
                for lead in c.source_leads
            ],
        )
        for c in result.candidates
    ]

    return TopicsGenerateResponse(
        job_id=job_id,
        round_number=round_.round_number,
        candidates=candidates,
        blocking_questions=result.blocking_questions,
    )


@router.post("/{job_id}/topics/select", response_model=TopicSelectResponse)
def select_topic(job_id: str, req: TopicSelectRequest):
    workflow = get_workflow()
    try:
        selected = workflow.select_topic(
            job_id=job_id,
            round_number=req.round_number,
            topic_id=req.topic_id,
        )
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job or topic not found.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return TopicSelectResponse(
        job_id=job_id,
        selected_topic_id=selected.topic_id,
        status="research_planning_ready",
    )


@router.post("/{job_id}/topics/reject", response_model=TopicRejectResponse)
def reject_topic(job_id: str, req: TopicRejectRequest):
    reason = req.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A rejection reason is required.")

    workflow = get_workflow()
    try:
        rejected = workflow.reject_topic(
            job_id=job_id,
            round_number=req.round_number,
            topic_id=req.topic_id,
            reason=reason,
        )
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job or topic not found.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return TopicRejectResponse(
        job_id=job_id,
        topic_id=rejected.topic_id,
        reason=rejected.reason,
    )
