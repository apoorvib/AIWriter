from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from difflib import SequenceMatcher

from llm.config import StageModelConfig
from essay_writer.drafting.revision import DraftRevisionService
from essay_writer.drafting.schema import DraftLens, EssayDraft
from essay_writer.drafting.storage import DraftStore
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.jobs.workflow import EssayWorkflow
from essay_writer.manual_revision.schema import (
    ManualRevisionMode,
    ManualRevisionRequest,
    ManualRevisionRun,
)
from essay_writer.manual_revision.storage import (
    ManualRevisionRequestStore,
    ManualRevisionRunStore,
)
from essay_writer.outlining.storage import ThesisOutlineStore
from essay_writer.research.storage import ResearchStore
from essay_writer.research_planning.storage import ResearchPlanStore
from essay_writer.sources.access import SourceAccessService
from essay_writer.sources.access_schema import SourceTextPacket
from essay_writer.sources.schema import SourceCard
from essay_writer.sources.storage import SourceStore
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.tone_alignment.service import ToneAlignmentService
from essay_writer.tone_alignment.schema import ToneAlignmentReport
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.validation.checks import run_deterministic_checks
from essay_writer.validation.schema import (
    AssignmentFit,
    DeterministicCheckResult,
    LengthCheck,
    LLMJudgmentResult,
    ValidationReport,
)
from essay_writer.validation.service import ValidationService
from essay_writer.writing_style.schema import WritingStylePayload
from essay_writer.writing_style.service import build_writing_style_payload
from essay_writer.writing_style.storage import HumanWritingSampleStore, WritingStyleContentStore


CORE_VALIDATION_LENSES: set[DraftLens] = {"evidence", "citations", "assignment_fit", "length"}
ALL_LENSES: set[DraftLens] = {*CORE_VALIDATION_LENSES, "tone", "anti_ai"}


class ManualRevisionService:
    def __init__(
        self,
        *,
        workflow: EssayWorkflow,
        task_store: TaskSpecStore,
        topic_store: TopicRoundStore,
        research_plan_store: ResearchPlanStore,
        research_store: ResearchStore,
        outline_store: ThesisOutlineStore,
        draft_store: DraftStore,
        export_store: FinalExportStore,
        request_store: ManualRevisionRequestStore,
        run_store: ManualRevisionRunStore,
        validation_service: ValidationService,
        tone_alignment_service: ToneAlignmentService | None,
        revision_service: DraftRevisionService,
        source_store: SourceStore | None,
        source_access_service: SourceAccessService | None,
        writing_style_sample_store: HumanWritingSampleStore | None,
        writing_style_content_store: WritingStyleContentStore | None,
        model_config: StageModelConfig | None = None,
    ) -> None:
        self._workflow = workflow
        self._task_store = task_store
        self._topic_store = topic_store
        self._research_plan_store = research_plan_store
        self._research_store = research_store
        self._outline_store = outline_store
        self._draft_store = draft_store
        self._export_store = export_store
        self._request_store = request_store
        self._run_store = run_store
        self._validation_service = validation_service
        self._tone_alignment_service = tone_alignment_service
        self._revision_service = revision_service
        self._source_store = source_store
        self._source_access_service = source_access_service
        self._writing_style_sample_store = writing_style_sample_store
        self._writing_style_content_store = writing_style_content_store
        self._model_config = model_config or StageModelConfig()

    def save_user_edit(
        self,
        *,
        job_id: str,
        content: str,
        base_draft_id: str | None = None,
        base_export_id: str | None = None,
    ) -> EssayDraft:
        text = content.strip()
        if not text:
            raise ValueError("Edited draft content is required.")
        if bool(base_draft_id) == bool(base_export_id):
            raise ValueError("Provide exactly one of base_draft_id or base_export_id.")

        job = self._workflow.load_job(job_id)
        if job.selected_topic_id is None:
            raise ValueError("Cannot save a user edit before a topic has been selected.")

        parent_draft: EssayDraft
        parent_export_id: str | None = None
        if base_export_id is not None:
            export = self._export_store.load(job_id, base_export_id)
            parent_draft = self._draft_store.find_by_id(job_id, export.draft_id)
            parent_export_id = export.id
        else:
            parent_draft = self._draft_store.find_by_id(job_id, base_draft_id or "")

        version = self._draft_store.next_version(job_id)
        draft = EssayDraft(
            id=_draft_id(version),
            job_id=job_id,
            version=version,
            selected_topic_id=parent_draft.selected_topic_id,
            content=text,
            outline_id=parent_draft.outline_id,
            citation_style=parent_draft.citation_style,
            section_source_map=list(parent_draft.section_source_map),
            bibliography_candidates=list(parent_draft.bibliography_candidates),
            known_weak_spots=list(parent_draft.known_weak_spots),
            origin="user_edit",
            created_by="user",
            parent_draft_id=parent_draft.id,
            parent_export_id=parent_export_id,
            prompt_version=parent_draft.prompt_version,
        )
        self._draft_store.save(draft)
        return draft

    def create_run(
        self,
        *,
        job_id: str,
        source_draft_id: str,
        mode: ManualRevisionMode,
        instruction: str | None,
        selected_lenses: list[DraftLens],
        model: str | None = None,
    ) -> tuple[ManualRevisionRequest, ManualRevisionRun, EssayDraft | None]:
        lenses = _normalize_lenses(selected_lenses)
        if not lenses:
            raise ValueError("Select at least one review lens.")

        job = self._workflow.load_job(job_id)
        if job.task_spec_id is None or job.selected_topic_id is None:
            raise ValueError("Manual reiteration requires a job with a completed drafting context.")

        source_draft = self._draft_store.find_by_id(job_id, source_draft_id)
        request_version = self._request_store.next_version(job_id)
        request = ManualRevisionRequest(
            id=f"manual_request_{request_version:03d}",
            job_id=job_id,
            source_draft_id=source_draft.id,
            mode=mode,
            instruction=(instruction or "").strip() or None,
            selected_lenses=lenses,
        )
        self._request_store.save(request, version=request_version)

        parent_draft = None
        if source_draft.parent_draft_id is not None:
            try:
                parent_draft = self._draft_store.find_by_id(job_id, source_draft.parent_draft_id)
            except KeyError:
                parent_draft = None
        change_summary = _summarize_changes(
            parent_draft.content if parent_draft is not None else None,
            source_draft.content,
        )

        task_spec = self._task_store.load_latest(job.task_spec_id)
        selected_topic = self._topic_store.load_selected_topic(job_id)
        research = self._research_store.load_latest(job_id)
        research_plan = self._research_plan_store.load_latest(job_id)
        outline = self._outline_store.load_latest(job_id)
        source_packets = self._resolve_source_packets(research_plan.source_requests)
        source_cards = self._load_source_cards(job.source_ids)
        writing_style_payload = self._load_writing_style_payload(job)

        warnings: list[str] = []
        pre_det = run_deterministic_checks(source_draft.content) if "anti_ai" in lenses else None
        pre_validation, pre_tone = self._run_reviews(
            draft=source_draft,
            task_spec=task_spec,
            bibliography_candidates=source_draft.bibliography_candidates,
            evidence_notes=research.evidence_map.notes,
            source_cards=source_cards,
            writing_style_payload=writing_style_payload,
            selected_lenses=lenses,
            warnings=warnings,
            model=model,
        )

        result_draft: EssayDraft | None = None
        post_validation = None
        post_tone = None
        post_det = None

        if mode == "revise":
            revision_validation = pre_validation or _synthetic_validation_report(
                draft=source_draft,
                task_spec_id=task_spec.id,
                det=pre_det or run_deterministic_checks(source_draft.content),
            )
            revised = self._revision_service.revise(
                job,
                task_spec,
                selected_topic,
                research.evidence_map,
                outline=outline,
                previous_draft=source_draft,
                validation=revision_validation,
                version=self._draft_store.next_version(job_id),
                source_packets=source_packets,
                writing_style_payload=writing_style_payload,
                tone_alignment=pre_tone,
                user_instruction=request.instruction,
                change_summary=change_summary,
                selected_lenses=lenses,
                model=model or self._model_config.drafting_revision,
            )
            result_draft = replace(
                revised,
                origin="manual_llm_revision",
                created_by="system",
                parent_draft_id=source_draft.id,
                parent_export_id=None,
                manual_request_id=request.id,
                user_instruction=request.instruction,
                selected_lenses=lenses,
            )
            self._draft_store.save(result_draft)
            post_det = run_deterministic_checks(result_draft.content) if "anti_ai" in lenses else None
            post_validation, post_tone = self._run_reviews(
                draft=result_draft,
                task_spec=task_spec,
                bibliography_candidates=result_draft.bibliography_candidates,
                evidence_notes=research.evidence_map.notes,
                source_cards=source_cards,
                writing_style_payload=writing_style_payload,
                selected_lenses=lenses,
                warnings=warnings,
                model=model,
            )

        run_version = self._run_store.next_version(job_id)
        run = ManualRevisionRun(
            id=f"manual_run_{run_version:03d}",
            request_id=request.id,
            job_id=job_id,
            source_draft_id=source_draft.id,
            mode=mode,
            instruction=request.instruction,
            selected_lenses=lenses,
            change_summary=change_summary,
            warnings=warnings,
            pre_revision_validation=pre_validation,
            pre_revision_tone_alignment=pre_tone,
            pre_revision_anti_ai=pre_det,
            result_draft_id=result_draft.id if result_draft is not None else None,
            post_revision_validation=post_validation,
            post_revision_tone_alignment=post_tone,
            post_revision_anti_ai=post_det,
        )
        self._run_store.save(run, version=run_version)
        return request, run, result_draft

    def list_runs(self, job_id: str) -> list[ManualRevisionRun]:
        return self._run_store.list_versions(job_id)

    def get_run(self, job_id: str, run_id: str) -> ManualRevisionRun:
        return self._run_store.find_by_id(job_id, run_id)

    def _load_writing_style_payload(self, job) -> WritingStylePayload | None:
        if (
            job.writing_style_content_id is None
            or not job.writing_style_sample_ids
            or self._writing_style_content_store is None
            or self._writing_style_sample_store is None
        ):
            return None
        content = self._writing_style_content_store.load(job.writing_style_content_id)
        samples = self._writing_style_sample_store.load_prompt_samples(job.writing_style_sample_ids)
        return build_writing_style_payload(content, samples)

    def _resolve_source_packets(self, source_requests) -> list[SourceTextPacket]:
        if self._source_access_service is None or not source_requests:
            return []
        return [
            packet
            for packet in self._source_access_service.resolve_locators(source_requests)
            if packet.text.strip()
        ]

    def _load_source_cards(self, source_ids: list[str]) -> list[SourceCard]:
        if self._source_store is None:
            return []
        cards: list[SourceCard] = []
        for source_id in source_ids:
            try:
                cards.append(self._source_store.load_source_card(source_id))
            except (FileNotFoundError, KeyError):
                continue
        return cards

    def _run_reviews(
        self,
        *,
        draft: EssayDraft,
        task_spec,
        bibliography_candidates: list[str],
        evidence_notes,
        source_cards: list[SourceCard],
        writing_style_payload: WritingStylePayload | None,
        selected_lenses: list[DraftLens],
        warnings: list[str],
        model: str | None,
    ) -> tuple[ValidationReport | None, ToneAlignmentReport | None]:
        need_validation = any(lens in CORE_VALIDATION_LENSES for lens in selected_lenses)
        need_tone = "tone" in selected_lenses
        validation = None
        tone = None
        if need_tone and writing_style_payload is None:
            warnings.append("Tone alignment was requested, but this job has no writing-style samples.")
            need_tone = False

        with ThreadPoolExecutor(max_workers=2 if need_validation and need_tone else 1) as executor:
            validation_future = (
                executor.submit(
                    self._validation_service.validate,
                    draft.content,
                    draft_id=draft.id,
                    task_spec=task_spec,
                    evidence_map=evidence_notes,
                    bibliography_candidates=bibliography_candidates,
                    source_cards=source_cards,
                    model=model or self._model_config.validation,
                )
                if need_validation
                else None
            )
            tone_future = (
                executor.submit(
                    self._tone_alignment_service.evaluate,
                    draft.content,
                    draft_id=draft.id,
                    task_spec=task_spec,
                    writing_style_payload=writing_style_payload,
                    model=model,
                )
                if need_tone and self._tone_alignment_service is not None and writing_style_payload is not None
                else None
            )
            if validation_future is not None:
                validation = validation_future.result()
            if tone_future is not None:
                tone = tone_future.result()
        return validation, tone


def _normalize_lenses(selected_lenses: list[DraftLens]) -> list[DraftLens]:
    seen: set[DraftLens] = set()
    normalized: list[DraftLens] = []
    for raw in selected_lenses:
        if raw not in ALL_LENSES:
            raise ValueError(f"Unsupported draft lens: {raw}")
        if raw in seen:
            continue
        seen.add(raw)
        normalized.append(raw)
    return normalized


def _synthetic_validation_report(
    *,
    draft: EssayDraft,
    task_spec_id: str,
    det: DeterministicCheckResult,
) -> ValidationReport:
    return ValidationReport(
        draft_id=draft.id,
        task_spec_id=task_spec_id,
        deterministic=det,
        llm_judgment=LLMJudgmentResult(
            unsupported_claims=[],
            citation_issues=[],
            rubric_scores=[],
            assignment_fit=AssignmentFit(passes=True, explanation="Manual core validation was not requested."),
            length_check=LengthCheck(actual_words=det.word_count, target_words=None, passes=True),
            style_issues=[],
            overall_quality=1.0,
            diagnostics=[],
            revision_suggestions=[],
        ),
    )


def _summarize_changes(parent_text: str | None, current_text: str) -> list[str]:
    if parent_text is None:
        return ["No parent draft was available for diffing. Treat this saved draft as the current base text."]

    normalized_parent = parent_text.strip()
    normalized_current = current_text.strip()
    if normalized_parent == normalized_current:
        return ["No textual changes were detected relative to the parent draft."]

    parent_words = _word_count(normalized_parent)
    current_words = _word_count(normalized_current)
    parent_paragraphs = _split_paragraphs(normalized_parent)
    current_paragraphs = _split_paragraphs(normalized_current)
    summary = [
        f"Word count changed from {parent_words} to {current_words}.",
        f"Paragraph count changed from {len(parent_paragraphs)} to {len(current_paragraphs)}.",
    ]

    matcher = SequenceMatcher(a=parent_paragraphs, b=current_paragraphs)
    replaced_ranges: list[str] = []
    inserted = 0
    deleted = 0
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "replace":
            replaced_ranges.append(_paragraph_range_text(j1 + 1, j2))
        elif opcode == "insert":
            inserted += j2 - j1
        elif opcode == "delete":
            deleted += i2 - i1

    if replaced_ranges:
        preview = ", ".join(replaced_ranges[:4])
        summary.append(f"Edited paragraph regions: {preview}.")
    if inserted:
        summary.append(f"Added {inserted} paragraph{'s' if inserted != 1 else ''}.")
    if deleted:
        summary.append(f"Removed {deleted} paragraph{'s' if deleted != 1 else ''}.")
    return summary


def _paragraph_range_text(start: int, end: int) -> str:
    if end <= start:
        return f"paragraph {start}"
    return f"paragraphs {start}-{end}"


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return paragraphs or [text.strip()]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _draft_id(version: int) -> str:
    return f"draft_manual_{version:03d}"
