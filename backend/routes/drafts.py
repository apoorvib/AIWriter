from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import get_draft_store, get_manual_revision_service, get_workflow
from backend.schemas import (
    AntiAiSummaryResponse,
    DraftResponse,
    DraftSummaryResponse,
    ExportResponse,
    ManualRevisionCreateRequest,
    ManualRevisionRunResponse,
    ManualRevisionRunSummaryResponse,
    SaveUserEditRequest,
    SectionSourceEntry,
    ToneAlignmentConflictResponse,
    ToneAlignmentSummaryResponse,
    ValidationDiagnosticResponse,
    ValidationSummary,
)
from essay_writer.drafting.schema import EssayDraft
from essay_writer.manual_revision.schema import ManualRevisionRun
from essay_writer.validation.schema import DeterministicCheckResult, ValidationReport

router = APIRouter(prefix="/jobs", tags=["drafts", "manual_revision"])


@router.get("/{job_id}/drafts", response_model=list[DraftSummaryResponse])
def list_drafts(job_id: str):
    workflow = get_workflow()
    try:
        workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")
    return [_draft_summary(draft) for draft in get_draft_store().list_versions(job_id)]


@router.get("/{job_id}/drafts/{version}", response_model=DraftResponse)
def get_draft(job_id: str, version: int):
    workflow = get_workflow()
    try:
        workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")
    try:
        draft = get_draft_store().load(job_id, version)
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return _draft_response(draft)


@router.post("/{job_id}/drafts/save-user-edit", response_model=DraftResponse)
def save_user_edit(job_id: str, req: SaveUserEditRequest):
    try:
        draft = get_manual_revision_service().save_user_edit(
            job_id=job_id,
            content=req.content,
            base_draft_id=req.base_draft_id,
            base_export_id=req.base_export_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _draft_response(draft)


@router.get("/{job_id}/manual-revision-runs", response_model=list[ManualRevisionRunSummaryResponse])
def list_manual_runs(job_id: str):
    workflow = get_workflow()
    try:
        workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")
    drafts = {draft.id: draft for draft in get_draft_store().list_versions(job_id)}
    return [_manual_run_summary(run, drafts) for run in get_manual_revision_service().list_runs(job_id)]


@router.get("/{job_id}/manual-revision-runs/{run_id}", response_model=ManualRevisionRunResponse)
def get_manual_run(job_id: str, run_id: str):
    workflow = get_workflow()
    try:
        workflow.load_job(job_id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Job not found.")
    drafts = {draft.id: draft for draft in get_draft_store().list_versions(job_id)}
    try:
        run = get_manual_revision_service().get_run(job_id, run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Manual revision run not found.")
    return _manual_run_response(run, drafts)


@router.post("/{job_id}/manual-revision-runs", response_model=ManualRevisionRunResponse)
def create_manual_run(job_id: str, req: ManualRevisionCreateRequest):
    try:
        _, run, result_draft = get_manual_revision_service().create_run(
            job_id=job_id,
            source_draft_id=req.source_draft_id,
            mode=req.mode,
            instruction=req.instruction,
            selected_lenses=list(req.selected_lenses),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    drafts = {draft.id: draft for draft in get_draft_store().list_versions(job_id)}
    if result_draft is not None:
        drafts[result_draft.id] = result_draft
    return _manual_run_response(run, drafts)


def _draft_summary(draft: EssayDraft) -> DraftSummaryResponse:
    return DraftSummaryResponse(
        draft_id=draft.id,
        version=draft.version,
        origin=draft.origin,
        created_by=draft.created_by,
        created_at=draft.created_at,
        parent_draft_id=draft.parent_draft_id,
        parent_export_id=draft.parent_export_id,
        manual_request_id=draft.manual_request_id,
        user_instruction=draft.user_instruction,
        selected_lenses=list(draft.selected_lenses),
        preview=_preview(draft.content),
    )


def _draft_response(draft: EssayDraft) -> DraftResponse:
    return DraftResponse(
        job_id=draft.job_id,
        draft_id=draft.id,
        version=draft.version,
        selected_topic_id=draft.selected_topic_id,
        content=draft.content,
        outline_id=draft.outline_id,
        citation_style=draft.citation_style,
        section_source_map=[
            SectionSourceEntry(
                section_id=section.section_id,
                heading=section.heading,
                note_ids=section.note_ids,
                source_ids=section.source_ids,
            )
            for section in draft.section_source_map
        ],
        bibliography_candidates=draft.bibliography_candidates,
        known_weak_spots=draft.known_weak_spots,
        origin=draft.origin,
        created_by=draft.created_by,
        parent_draft_id=draft.parent_draft_id,
        parent_export_id=draft.parent_export_id,
        manual_request_id=draft.manual_request_id,
        user_instruction=draft.user_instruction,
        selected_lenses=list(draft.selected_lenses),
        created_at=draft.created_at,
    )


def _manual_run_summary(run: ManualRevisionRun, drafts: dict[str, EssayDraft]) -> ManualRevisionRunSummaryResponse:
    source_draft = drafts.get(run.source_draft_id)
    result_draft = drafts.get(run.result_draft_id or "")
    return ManualRevisionRunSummaryResponse(
        run_id=run.id,
        request_id=run.request_id,
        source_draft_id=run.source_draft_id,
        source_draft_version=source_draft.version if source_draft is not None else None,
        result_draft_id=run.result_draft_id,
        result_draft_version=result_draft.version if result_draft is not None else None,
        mode=run.mode,
        selected_lenses=list(run.selected_lenses),
        status=run.status,
        created_at=run.created_at,
    )


def _manual_run_response(run: ManualRevisionRun, drafts: dict[str, EssayDraft]) -> ManualRevisionRunResponse:
    source_draft = drafts.get(run.source_draft_id)
    result_draft = drafts.get(run.result_draft_id or "")
    return ManualRevisionRunResponse(
        run_id=run.id,
        request_id=run.request_id,
        source_draft_id=run.source_draft_id,
        source_draft_version=source_draft.version if source_draft is not None else None,
        result_draft_id=run.result_draft_id,
        result_draft_version=result_draft.version if result_draft is not None else None,
        mode=run.mode,
        instruction=run.instruction,
        selected_lenses=list(run.selected_lenses),
        change_summary=list(run.change_summary),
        warnings=list(run.warnings),
        status=run.status,
        created_at=run.created_at,
        pre_revision_validation=_validation_summary(run.pre_revision_validation)
        if run.pre_revision_validation is not None
        else None,
        pre_revision_tone_alignment=_tone_summary(run.pre_revision_tone_alignment)
        if run.pre_revision_tone_alignment is not None
        else None,
        pre_revision_anti_ai=_anti_ai_summary(run.pre_revision_anti_ai)
        if run.pre_revision_anti_ai is not None
        else None,
        post_revision_validation=_validation_summary(run.post_revision_validation)
        if run.post_revision_validation is not None
        else None,
        post_revision_tone_alignment=_tone_summary(run.post_revision_tone_alignment)
        if run.post_revision_tone_alignment is not None
        else None,
        post_revision_anti_ai=_anti_ai_summary(run.post_revision_anti_ai)
        if run.post_revision_anti_ai is not None
        else None,
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


def _tone_summary(report) -> ToneAlignmentSummaryResponse:
    return ToneAlignmentSummaryResponse(
        overall_alignment=report.overall_alignment,
        requires_revision=report.requires_revision,
        matched_habits=report.matched_habits,
        mismatched_habits=report.mismatched_habits,
        preserve_points=report.preserve_points,
        revision_targets=report.revision_targets,
        anti_ai_conflicts=[
            ToneAlignmentConflictResponse(
                issue_type=item.issue_type,
                anti_ai_signal=item.anti_ai_signal,
                tone_signal=item.tone_signal,
                resolution=item.resolution,
                rationale=item.rationale,
            )
            for item in report.anti_ai_conflicts
        ],
    )


def _anti_ai_summary(det: DeterministicCheckResult) -> AntiAiSummaryResponse:
    profile = det.paragraph_length_profile
    return AntiAiSummaryResponse(
        word_count=det.word_count,
        em_dash_count=det.em_dash_count,
        en_dash_count=det.en_dash_count,
        decorative_hyphen_pause_count=det.decorative_hyphen_pause_count,
        colon_explanation_pattern_count=det.colon_explanation_pattern_count,
        triplet_contrastive_combo_count=det.triplet_contrastive_combo_count,
        clustered_triplet_count=det.clustered_triplet_count,
        participial_phrase_count=det.participial_phrase_count,
        participial_phrase_rate=det.participial_phrase_rate,
        contrastive_negation_count=det.contrastive_negation_count,
        bad_conclusion_opener=det.bad_conclusion_opener,
        concrete_engagement_present=det.concrete_engagement_present,
        paragraph_length_variance_warning=det.paragraph_length_variance_warning,
        mechanical_burstiness_count=det.mechanical_burstiness_count,
        tier1_vocab_hits=[{"word": item.word, "count": item.count} for item in det.tier1_vocab_hits],
        signposting_hits=list(det.signposting_hits),
        consecutive_similar_sentence_runs=[
            {"sentence_count": item.sentence_count, "avg_word_count": item.avg_word_count}
            for item in det.consecutive_similar_sentence_runs
        ],
        paragraph_length_profile=(
            {
                "paragraph_count": profile.paragraph_count,
                "shortest_word_count": profile.shortest_word_count,
                "longest_word_count": profile.longest_word_count,
                "longest_to_shortest_ratio": profile.longest_to_shortest_ratio,
            }
            if profile is not None
            else None
        ),
    )


def _preview(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
