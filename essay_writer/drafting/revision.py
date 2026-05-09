from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from llm.client import LLMClient, UserBlock
from essay_writer.drafting.prompts import DRAFTING_SCHEMA, DRAFTING_SYSTEM_PROMPT
from essay_writer.drafting.schema import DraftLens, EssayDraft, SectionSourceMap
from essay_writer.drafting.service import build_static_drafting_context_json
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import ThesisOutline
from essay_writer.research.schema import EvidenceMap
from essay_writer.sources.access_schema import SourceTextPacket
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.tone_alignment.schema import ToneAlignmentReport
from essay_writer.topic_ideation.schema import SelectedTopic
from essay_writer.validation.schema import ValidationReport
from essay_writer.writing_style.prompts import build_writing_style_prompt_block
from essay_writer.writing_style.schema import WritingStylePayload


class DraftRevisionService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "drafting-revision-v1",
        max_tokens: int = 8000,
    ) -> None:
        self._llm = llm_client
        self._prompt_version = prompt_version
        self._max_tokens = max_tokens

    def revise(
        self,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        evidence_map: EvidenceMap,
        *,
        outline: ThesisOutline,
        previous_draft: EssayDraft,
        validation: ValidationReport,
        version: int,
        source_packets: list[SourceTextPacket] | None = None,
        writing_style_payload: WritingStylePayload | None = None,
        tone_alignment: ToneAlignmentReport | None = None,
        user_instruction: str | None = None,
        change_summary: list[str] | None = None,
        selected_lenses: list[DraftLens] | None = None,
        model: str | None = None,
    ) -> EssayDraft:
        payload = self._llm.chat_json(
            system=DRAFTING_SYSTEM_PROMPT,
            user=_build_revision_blocks(
                task_spec=task_spec,
                selected_topic=selected_topic,
                evidence_map=evidence_map,
                outline=outline,
                previous_draft=previous_draft,
                validation=validation,
                source_packets=source_packets or [],
                writing_style_payload=writing_style_payload,
                tone_alignment=tone_alignment,
                user_instruction=user_instruction,
                change_summary=change_summary or [],
            ),
            json_schema=DRAFTING_SCHEMA,
            max_tokens=self._max_tokens,
            model=model,
        )
        revised = _draft_from_payload(
            payload,
            job=job,
            selected_topic=selected_topic,
            task_spec=task_spec,
            outline=outline,
            version=version,
            prompt_version=self._prompt_version,
        )
        return replace(
            revised,
            origin="system_revision",
            created_by="system",
            parent_draft_id=previous_draft.id,
            manual_request_id=None,
            user_instruction=user_instruction,
            selected_lenses=list(selected_lenses or []),
        )


def _build_revision_blocks(
    *,
    task_spec: TaskSpecification,
    selected_topic: SelectedTopic,
    evidence_map: EvidenceMap,
    outline: ThesisOutline,
    previous_draft: EssayDraft,
    validation: ValidationReport,
    source_packets: list[SourceTextPacket],
    writing_style_payload: WritingStylePayload | None,
    tone_alignment: ToneAlignmentReport | None,
    user_instruction: str | None,
    change_summary: list[str],
) -> list[UserBlock]:
    """Build the revision user message as a cacheable static block plus a
    mutable suffix.

    The static block is byte-identical to the drafting-stage static block (see
    drafting.service.build_static_drafting_context_json) so that within the
    Anthropic prompt-cache TTL, revision calls hit the cache for the whole
    task_spec + selected_topic + evidence + outline + source_packets payload.
    The mutable block carries the revision instruction text, the validation
    diagnostics, the previous draft body, and any tone/style payloads.
    """
    revision_context = {
        "revision_task": {
            "previous_draft_id": previous_draft.id,
            "previous_draft_version": previous_draft.version,
            "validation_passed": validation.passes,
            "deterministic_style_issues": _deterministic_style_payload(validation),
            "unsupported_claims": [
                {"claim": item.claim, "paragraph": item.paragraph}
                for item in validation.llm_judgment.unsupported_claims
            ],
            "citation_issues": [
                {"description": item.description, "severity": item.severity}
                for item in validation.llm_judgment.citation_issues
            ],
            "metadata_citation_warnings": [
                {
                    "source_id": item.source_id,
                    "description": item.description,
                    "severity": item.severity,
                }
                for item in validation.metadata_citation_warnings
            ],
            "style_issues": [
                {"issue_type": item.issue_type, "description": item.description}
                for item in validation.llm_judgment.style_issues
            ],
            "diagnostics": [
                {
                    "location": item.location,
                    "issue_type": item.issue_type,
                    "evidence": item.evidence,
                    "severity": item.severity,
                    "action": item.action,
                }
                for item in validation.llm_judgment.diagnostics
            ],
            "revision_suggestions": validation.llm_judgment.revision_suggestions,
            "known_weak_spots": previous_draft.known_weak_spots,
            "manual_reiteration": {
                "user_instruction": user_instruction,
                "change_summary": change_summary,
            },
            "tone_alignment": (
                {
                    "overall_alignment": tone_alignment.overall_alignment,
                    "requires_revision": tone_alignment.requires_revision,
                    "matched_habits": tone_alignment.matched_habits,
                    "mismatched_habits": tone_alignment.mismatched_habits,
                    "preserve_points": tone_alignment.preserve_points,
                    "revision_targets": tone_alignment.revision_targets,
                    "anti_ai_conflicts": [
                        {
                            "issue_type": item.issue_type,
                            "anti_ai_signal": item.anti_ai_signal,
                            "tone_signal": item.tone_signal,
                            "resolution": item.resolution,
                            "rationale": item.rationale,
                        }
                        for item in tone_alignment.anti_ai_conflicts
                    ],
                }
                if tone_alignment is not None
                else None
            ),
        },
        "previous_draft": {
            "content": previous_draft.content,
            "section_source_map": [
                {
                    "section_id": section.section_id,
                    "heading": section.heading,
                    "note_ids": section.note_ids,
                    "source_ids": section.source_ids,
                }
                for section in previous_draft.section_source_map
            ],
            "bibliography_candidates": previous_draft.bibliography_candidates,
        },
    }
    static_block = build_static_drafting_context_json(
        task_spec, selected_topic, evidence_map, outline, source_packets
    )
    instruction = (
        "Revise the previous draft using the structured validation diagnostics while keeping every "
        "claim grounded in the supplied evidence. Fix diagnosed locations without copying validator "
        "wording. Do not add unsupported facts, unsupported citations, short filler sentences just "
        "to vary rhythm, or clipped fragment chains like 'It can advise. It cannot compel.' "
        "If manual_reiteration.user_instruction is present, follow it while preserving the user's "
        "edited text as the base document rather than regenerating from an older draft. "
        "If tone_alignment is present and it conflicts with generic anti-AI heuristics, prefer the "
        "user's authentic tone and writing habits while still removing clear machine-like artifacts."
    )
    mutable_parts = [
        "\n\n",
        instruction,
        "\n\n",
        json.dumps(revision_context, ensure_ascii=False),
    ]
    if writing_style_payload is not None:
        mutable_parts.append("\n\n")
        mutable_parts.append(build_writing_style_prompt_block(writing_style_payload))
    mutable_block = "".join(mutable_parts)
    return [
        UserBlock(text=static_block, cacheable=True),
        UserBlock(text=mutable_block, cacheable=False),
    ]


def _deterministic_style_payload(validation: ValidationReport) -> dict[str, Any]:
    det = validation.deterministic
    return {
        "em_dash_count": det.em_dash_count,
        "en_dash_count": det.en_dash_count,
        "decorative_hyphen_pause_count": det.decorative_hyphen_pause_count,
        "colon_explanation_pattern_count": det.colon_explanation_pattern_count,
        "tier1_vocab_hits": [{"word": item.word, "count": item.count} for item in det.tier1_vocab_hits],
        "bad_conclusion_opener": det.bad_conclusion_opener,
        "consecutive_similar_sentence_runs": len(det.consecutive_similar_sentence_runs),
        "participial_phrase_count": det.participial_phrase_count,
        "participial_phrase_rate_per_300_words": round(det.participial_phrase_rate, 2),
        "contrastive_negation_count": det.contrastive_negation_count,
        "signposting_hits": det.signposting_hits,
        "triplet_contrastive_combo_count": det.triplet_contrastive_combo_count,
        "clustered_triplet_count": det.clustered_triplet_count,
        "paragraph_length_variance_warning": det.paragraph_length_variance_warning,
        "mechanical_burstiness_count": det.mechanical_burstiness_count,
        "concrete_engagement_present": det.concrete_engagement_present,
    }


def _draft_from_payload(
    payload: dict[str, Any],
    *,
    job: EssayJob,
    selected_topic: SelectedTopic,
    task_spec: TaskSpecification,
    outline: ThesisOutline,
    version: int,
    prompt_version: str,
) -> EssayDraft:
    section_source_map = [
        SectionSourceMap(
            section_id=str(item.get("section_id", "")).strip(),
            heading=str(item.get("heading", "")).strip(),
            note_ids=_payload_list(item, "note_ids", max_items=50),
            source_ids=_payload_list(item, "source_ids", max_items=20),
        )
        for item in payload.get("section_source_map", [])
        if str(item.get("section_id", "")).strip()
    ]
    return EssayDraft(
        id=f"draft_{uuid4().hex[:12]}",
        job_id=job.id,
        version=version,
        selected_topic_id=selected_topic.topic_id,
        content=str(payload.get("content", "")).strip(),
        outline_id=outline.id,
        citation_style=task_spec.citation_style,
        section_source_map=section_source_map,
        bibliography_candidates=_payload_list(payload, "bibliography_candidates", max_items=50),
        known_weak_spots=_payload_list(payload, "known_weak_spots", max_items=20),
        prompt_version=prompt_version,
    )


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value[:max_items] if str(item).strip()]


