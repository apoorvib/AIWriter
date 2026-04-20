from __future__ import annotations

import json

from essay_writer.sources.schema import SourceCard, SourceIndexManifest
from essay_writer.sources.access_schema import SourceMap
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import CandidateTopic, RejectedTopic


def build_topic_ideation_context(
    task_spec: TaskSpecification,
    *,
    source_cards: list[SourceCard],
    index_manifests: list[SourceIndexManifest] | None = None,
    source_maps: list[SourceMap] | None = None,
    previous_candidates: list[CandidateTopic] | None = None,
    rejected_topics: list[RejectedTopic] | None = None,
    user_instruction: str | None = None,
    source_card_max_chars: int = 4_000,
    index_preview_chars: int = 180,
    max_manifest_entries: int | None = None,
    max_source_map_units: int = 120,
) -> str:
    payload = {
        "task_specification": _task_spec_payload(task_spec),
        "user_instruction": user_instruction,
        "previous_candidates": [
            _candidate_payload(candidate) for candidate in (previous_candidates or [])
        ],
        "rejected_topics": [
            _rejected_payload(rejected) for rejected in (rejected_topics or [])
        ],
        "source_cards": [
            {
                "source_id": card.source_id,
                "context": card.to_context(max_chars=source_card_max_chars),
            }
            for card in source_cards
        ],
        "source_index_manifests": [
            {
                "source_id": manifest.source_id,
                "index_handle": manifest.source_id,
                "context": manifest.to_context(
                    max_preview_chars=index_preview_chars,
                    max_entries=max_manifest_entries,
                ),
            }
            for manifest in (index_manifests or [])
        ],
        "source_maps": [
            {
                "source_id": source_map.source_id,
                "context": source_map.to_context(max_units=max_source_map_units),
            }
            for source_map in (source_maps or [])
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _task_spec_payload(task_spec: TaskSpecification) -> dict:
    return {
        "id": task_spec.id,
        "version": task_spec.version,
        "assignment_title": task_spec.assignment_title,
        "essay_type": task_spec.essay_type,
        "academic_level": task_spec.academic_level,
        "target_length": task_spec.target_length,
        "length_unit": task_spec.length_unit,
        "citation_style": task_spec.citation_style,
        "topic_scope": task_spec.topic_scope,
        "selected_prompt": task_spec.selected_prompt,
        "prompt_options": task_spec.prompt_options,
        "required_sources": task_spec.required_sources,
        "allowed_sources": task_spec.allowed_sources,
        "forbidden_sources": task_spec.forbidden_sources,
        "required_materials": task_spec.required_materials,
        "required_claims_or_questions": task_spec.required_claims_or_questions,
        "required_structure": task_spec.required_structure,
        "formatting_requirements": task_spec.formatting_requirements,
        "rubric": task_spec.rubric,
        "grading_criteria": task_spec.grading_criteria,
        "professor_constraints": task_spec.professor_constraints,
        "blocking_questions": task_spec.blocking_questions,
        "nonblocking_warnings": task_spec.nonblocking_warnings,
        "extracted_checklist": [
            {
                "id": item.id,
                "text": item.text,
                "category": item.category,
                "required": item.required,
                "source_span": item.source_span,
            }
            for item in task_spec.extracted_checklist
        ],
        "adversarial_flags_present": bool(task_spec.adversarial_flags),
    }


def _candidate_payload(candidate: CandidateTopic) -> dict:
    return {
        "id": candidate.id,
        "title": candidate.title,
        "research_question": candidate.research_question,
        "tentative_thesis_direction": candidate.tentative_thesis_direction,
        "rationale": candidate.rationale,
        "source_ids": [lead.source_id for lead in candidate.source_leads],
        "chunk_ids": [
            chunk_id
            for lead in candidate.source_leads
            for chunk_id in lead.chunk_ids
        ],
        "risk_flags": candidate.risk_flags,
        "missing_evidence": candidate.missing_evidence,
    }


def _rejected_payload(rejected: RejectedTopic) -> dict:
    return {
        "topic_id": rejected.topic_id,
        "title": rejected.title,
        "reason": rejected.reason,
    }
