from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from llm.client import LLMClient, UserBlock
from essay_writer.drafting.anti_ai_skill import ANTI_AI_SKILL_DOCUMENT
from essay_writer.drafting.schema import EssayDraft
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import ThesisOutline
from essay_writer.research.schema import EvidenceMap
from essay_writer.sources.access_schema import SourceTextPacket
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.validation.checks import run_deterministic_checks
from essay_writer.validation.schema import DeterministicCheckResult
from essay_writer.writing_style.prompts import build_writing_style_prompt_block
from essay_writer.writing_style.schema import WritingStylePayload


STYLE_REVISION_SYSTEM_PROMPT = f"""You perform a final prose-only style pass on an academic essay draft.

The goal is to reduce AI-like prose patterns while preserving the draft's meaning, factual claims,
citations, source grounding, section source map, and bibliography candidates.

Hard constraints:
- Do not add facts, examples, citations, source names, quotes, page numbers, or statistics.
- Do not remove required source-backed claims.
- Do not change the thesis meaning.
- Do not copy validator-style language into the essay.
- Do not add short filler sentences just to vary rhythm.
- Do not create clipped fragment chains like "X is limited. It can advise. It cannot compel."
- Only revise prose shape, rhythm, transitions, generic phrasing, paragraph movement, and source engagement phrasing.
- If real writing samples are supplied, use them only to preserve the user's authentic voice.
- When generic anti-AI heuristics conflict with the user's real writing style, preserve the authentic voice unless the pattern is clearly machine-like.

Apply the anti-AI writing skill during this pass.

<anti_ai_detection_skill>
{ANTI_AI_SKILL_DOCUMENT}
</anti_ai_detection_skill>
"""


STYLE_REVISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["content", "style_changes", "preservation_notes", "known_risks"],
    "properties": {
        "content": {"type": "string"},
        "style_changes": {"type": "array", "items": {"type": "string"}},
        "preservation_notes": {"type": "array", "items": {"type": "string"}},
        "known_risks": {"type": "array", "items": {"type": "string"}},
    },
}


class FinalStyleRevisionService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "drafting-style-revision-v1",
        max_tokens: int = 8000,
    ) -> None:
        self._llm = llm_client
        self._prompt_version = prompt_version
        self._max_tokens = max_tokens

    def revise_style(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        draft: EssayDraft,
        outline: ThesisOutline,
        evidence_map: EvidenceMap,
        source_packets: list[SourceTextPacket] | None = None,
        writing_style_payload: WritingStylePayload | None = None,
        version: int,
        model: str | None = None,
    ) -> EssayDraft:
        payload = self._llm.chat_json(
            system=STYLE_REVISION_SYSTEM_PROMPT,
            user=_build_user_message(
                task_spec=task_spec,
                draft=draft,
                outline=outline,
                evidence_map=evidence_map,
                source_packets=source_packets or [],
                writing_style_payload=writing_style_payload,
            ),
            json_schema=STYLE_REVISION_SCHEMA,
            max_tokens=self._max_tokens,
            model=model,
        )
        content = str(payload.get("content", "")).strip() or draft.content
        risks = _payload_list(payload, "known_risks", max_items=20)
        weak_spots = risks if risks else list(draft.known_weak_spots)
        return replace(
            draft,
            id=f"draft_{uuid4().hex[:12]}",
            version=version,
            content=content,
            known_weak_spots=weak_spots,
            origin="style_revision",
            created_by="system",
            parent_draft_id=draft.id,
            parent_export_id=None,
            manual_request_id=None,
            user_instruction=None,
            selected_lenses=[],
            prompt_version=self._prompt_version,
        )


def build_style_revision_static_context_json(
    *,
    task_spec: TaskSpecification,
    draft: EssayDraft,
    outline: ThesisOutline,
    evidence_map: EvidenceMap,
    source_packets: list[SourceTextPacket],
    det: DeterministicCheckResult,
) -> str:
    """Serialize the static style-revision context as a JSON string.

    Shared between Pipeline Mode (`FinalStyleRevisionService`) and Agent Tool
    Mode (`prepare_style_revision`) so both paths submit identical prompts to
    the LLM. Field order is fixed; do not reorder without invalidating the
    Anthropic prompt cache."""
    context = _style_revision_context(
        task_spec=task_spec,
        draft=draft,
        outline=outline,
        evidence_map=evidence_map,
        source_packets=source_packets,
        det=det,
    )
    return json.dumps(context, ensure_ascii=False)


def build_style_revision_user_blocks(
    *,
    task_spec: TaskSpecification,
    draft: EssayDraft,
    outline: ThesisOutline,
    evidence_map: EvidenceMap,
    source_packets: list[SourceTextPacket],
    det: DeterministicCheckResult,
    writing_style_payload: WritingStylePayload | None,
) -> list[UserBlock]:
    """Split the style-revision user message into a cacheable static block plus
    an optional writing-style suffix block. Mirrors `build_drafting_user_blocks`
    so prompt caching behavior matches between drafting and the style pass."""
    static_json = build_style_revision_static_context_json(
        task_spec=task_spec,
        draft=draft,
        outline=outline,
        evidence_map=evidence_map,
        source_packets=source_packets,
        det=det,
    )
    if writing_style_payload is None:
        return [UserBlock(text=static_json, cacheable=True)]
    suffix = f"\n\n{build_writing_style_prompt_block(writing_style_payload)}"
    return [
        UserBlock(text=static_json, cacheable=True),
        UserBlock(text=suffix, cacheable=False),
    ]


def _build_user_message(
    *,
    task_spec: TaskSpecification,
    draft: EssayDraft,
    outline: ThesisOutline,
    evidence_map: EvidenceMap,
    source_packets: list[SourceTextPacket],
    writing_style_payload: WritingStylePayload | None,
) -> str:
    det = run_deterministic_checks(draft.content)
    blocks = build_style_revision_user_blocks(
        task_spec=task_spec,
        draft=draft,
        outline=outline,
        evidence_map=evidence_map,
        source_packets=source_packets,
        det=det,
        writing_style_payload=writing_style_payload,
    )
    return "".join(block.text for block in blocks)


def _style_revision_context(
    *,
    task_spec: TaskSpecification,
    draft: EssayDraft,
    outline: ThesisOutline,
    evidence_map: EvidenceMap,
    source_packets: list[SourceTextPacket],
    det: DeterministicCheckResult,
) -> dict[str, Any]:
    context = {
        "task_spec": {
            "essay_type": task_spec.essay_type,
            "academic_level": task_spec.academic_level,
            "target_length": task_spec.target_length,
            "length_unit": task_spec.length_unit,
            "citation_style": task_spec.citation_style,
            "rubric": task_spec.rubric,
            "required_structure": task_spec.required_structure,
            "professor_constraints": task_spec.professor_constraints,
        },
        "deterministic_style_issues": {
            "em_dash_count": det.em_dash_count,
            "en_dash_count": det.en_dash_count,
            "decorative_hyphen_pause_count": det.decorative_hyphen_pause_count,
            "colon_explanation_pattern_count": det.colon_explanation_pattern_count,
            "tier1_vocab_hits": [{"word": hit.word, "count": hit.count} for hit in det.tier1_vocab_hits],
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
        },
        "outline": {
            "outline_id": outline.id,
            "working_thesis": outline.working_thesis,
            "sections": [
                {
                    "id": section.id,
                    "heading": section.heading,
                    "purpose": section.purpose,
                    "key_points": section.key_points,
                    "note_ids": section.note_ids,
                    "target_words": section.target_words,
                }
                for section in outline.sections
            ],
        },
        "evidence_map": {
            "notes": [
                {
                    "id": note.id,
                    "source_id": note.source_id,
                    "page_start": note.page_start,
                    "page_end": note.page_end,
                    "claim": note.claim,
                    "quote": note.quote,
                    "paraphrase": note.paraphrase,
                    "evidence_type": note.evidence_type,
                }
                for note in evidence_map.notes
            ],
            "gaps": evidence_map.gaps,
            "conflicts": evidence_map.conflicts,
        },
        "source_packets": [
            {
                "packet_id": packet.packet_id,
                "source_id": packet.source_id,
                "locator_type": packet.locator.locator_type,
                "pdf_page_start": packet.pdf_page_start,
                "pdf_page_end": packet.pdf_page_end,
                "printed_page_start": packet.printed_page_start,
                "printed_page_end": packet.printed_page_end,
                "heading_path": packet.heading_path,
                "extraction_method": packet.extraction_method,
                "text_quality": packet.text_quality,
                "warnings": packet.warnings,
                "text": packet.text,
            }
            for packet in source_packets
        ],
        "draft": {
            "draft_id": draft.id,
            "version": draft.version,
            "content": draft.content,
            "section_source_map": [
                {
                    "section_id": section.section_id,
                    "heading": section.heading,
                    "note_ids": section.note_ids,
                    "source_ids": section.source_ids,
                }
                for section in draft.section_source_map
            ],
            "bibliography_candidates": draft.bibliography_candidates,
            "known_weak_spots": draft.known_weak_spots,
        },
    }
    return context


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value[:max_items] if str(item).strip()]
