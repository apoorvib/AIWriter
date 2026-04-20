from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from llm.client import LLMClient
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import ThesisOutline
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic
from essay_writer.research.schema import EvidenceMap
from essay_writer.sources.access_schema import SourceTextPacket
from essay_writer.drafting.prompts import DRAFTING_SCHEMA, DRAFTING_SYSTEM_PROMPT
from essay_writer.drafting.schema import EssayDraft, SectionSourceMap


class DraftService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "drafting-v1",
    ) -> None:
        self._llm = llm_client
        self._prompt_version = prompt_version

    def generate(
        self,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        evidence_map: EvidenceMap,
        *,
        outline: ThesisOutline | None = None,
        source_packets: list[SourceTextPacket] | None = None,
        version: int = 1,
        model: str | None = None,
    ) -> EssayDraft:
        payload = self._llm.chat_json(
            system=DRAFTING_SYSTEM_PROMPT,
            user=_build_user_message(
                task_spec,
                selected_topic,
                evidence_map,
                outline,
                source_packets or [],
            ),
            json_schema=DRAFTING_SCHEMA,
            max_tokens=8000,
            model=model,
        )
        return _draft_from_payload(
            payload,
            job=job,
            selected_topic=selected_topic,
            task_spec=task_spec,
            outline=outline,
            version=version,
            prompt_version=self._prompt_version,
        )


def _build_user_message(
    task_spec: TaskSpecification,
    selected_topic: SelectedTopic,
    evidence_map: EvidenceMap,
    outline: ThesisOutline | None,
    source_packets: list[SourceTextPacket],
) -> str:
    context = {
        "task_spec": {
            "essay_type": task_spec.essay_type,
            "academic_level": task_spec.academic_level,
            "target_length": task_spec.target_length,
            "length_unit": task_spec.length_unit,
            "citation_style": task_spec.citation_style,
            "rubric": task_spec.rubric,
            "required_structure": task_spec.required_structure,
            "selected_prompt": task_spec.selected_prompt,
            "professor_constraints": task_spec.professor_constraints,
            "extracted_checklist": [
                {"id": item.id, "text": item.text, "category": item.category, "required": item.required}
                for item in task_spec.extracted_checklist
            ],
        },
        "selected_topic": {
            "topic_id": selected_topic.topic_id,
            "title": selected_topic.title,
            "research_question": selected_topic.research_question,
            "thesis_direction": selected_topic.tentative_thesis_direction,
        },
        "evidence": {
            "notes": [
                {
                    "id": note.id,
                    "source_id": note.source_id,
                    "page_start": note.page_start,
                    "page_end": note.page_end,
                    "claim": note.claim,
                    "paraphrase": note.paraphrase,
                    "quote": note.quote,
                    "evidence_type": note.evidence_type,
                    "supports_topic": note.supports_topic,
                }
                for note in evidence_map.notes
            ],
            "evidence_groups": [
                {
                    "id": group.id,
                    "label": group.label,
                    "purpose": group.purpose,
                    "note_ids": group.note_ids,
                    "synthesis": group.synthesis,
                }
                for group in evidence_map.evidence_groups
            ],
            "gaps": evidence_map.gaps,
            "conflicts": evidence_map.conflicts,
        },
    }
    if outline is not None:
        context["outline"] = {
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
        }
    context["source_packets"] = _source_packets_payload(source_packets)
    return json.dumps(context, ensure_ascii=False)


def _source_packets_payload(source_packets: list[SourceTextPacket]) -> list[dict[str, Any]]:
    return [
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
    ]


def _draft_from_payload(
    payload: dict[str, Any],
    *,
    job: EssayJob,
    selected_topic: SelectedTopic,
    task_spec: TaskSpecification,
    outline: ThesisOutline | None,
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
        outline_id=outline.id if outline is not None else None,
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
