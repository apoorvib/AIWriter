from __future__ import annotations

import json
from typing import Any

from llm.client import LLMClient
from essay_writer.jobs.schema import EssayJob
from essay_writer.research.prompts import FINAL_TOPIC_RESEARCH_SCHEMA, FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT
from essay_writer.research.schema import (
    EvidenceGroup,
    EvidenceMap,
    FinalTopicResearchResult,
    ResearchNote,
    ResearchReport,
)
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.sources.access_schema import SourceTextPacket
from essay_writer.topic_ideation.schema import RetrievedTopicEvidence, SelectedTopic, TopicEvidenceChunk


class ResearchValidationWarning(RuntimeError):
    """Marker type for research validation warnings."""


class FinalTopicResearchService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "final-topic-research-v1",
        max_notes: int = 80,
    ) -> None:
        if max_notes < 1:
            raise ValueError("max_notes must be >= 1")
        self._llm = llm_client
        self._prompt_version = prompt_version
        self._max_notes = max_notes

    def extract(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        retrieved_evidence: list[RetrievedTopicEvidence],
        source_packets: list[SourceTextPacket] | None = None,
        evidence_map_version: int = 1,
        model: str | None = None,
        enable_web_search: bool = False,
    ) -> FinalTopicResearchResult:
        chunks = [
            *_packet_chunks(source_packets or []),
            *_flatten_chunks(selected_topic.topic_id, retrieved_evidence),
        ]
        if not chunks:
            return _empty_result(
                job=job,
                selected_topic=selected_topic,
                evidence_map_version=evidence_map_version,
                prompt_version=self._prompt_version,
                warning="No retrieved source chunks were available for final topic research.",
            )

        payload = self._llm.chat_json(
            system=FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT,
            user=_build_user_message(job, task_spec, selected_topic, chunks, self._max_notes),
            json_schema=FINAL_TOPIC_RESEARCH_SCHEMA,
            max_tokens=8000,
            model=model,
            enable_web_search=enable_web_search,
        )
        return _result_from_payload(
            job=job,
            selected_topic=selected_topic,
            chunks=chunks,
            payload=payload,
            evidence_map_version=evidence_map_version,
            prompt_version=self._prompt_version,
            max_notes=self._max_notes,
        )


def _build_user_message(
    job: EssayJob,
    task_spec: TaskSpecification,
    selected_topic: SelectedTopic,
    chunks: list[TopicEvidenceChunk],
    max_notes: int,
) -> str:
    return json.dumps(
        {
            "job": {
                "job_id": job.id,
                "task_spec_id": job.task_spec_id,
            },
            "task_specification": {
                "id": task_spec.id,
                "essay_type": task_spec.essay_type,
                "academic_level": task_spec.academic_level,
                "target_length": task_spec.target_length,
                "length_unit": task_spec.length_unit,
                "citation_style": task_spec.citation_style,
                "selected_prompt": task_spec.selected_prompt,
                "required_sources": task_spec.required_sources,
                "required_structure": task_spec.required_structure,
                "rubric": task_spec.rubric,
                "extracted_checklist": [
                    {
                        "id": item.id,
                        "text": item.text,
                        "category": item.category,
                        "required": item.required,
                    }
                    for item in task_spec.extracted_checklist
                ],
            },
            "selected_topic": {
                "topic_id": selected_topic.topic_id,
                "title": selected_topic.title,
                "research_question": selected_topic.research_question,
                "tentative_thesis_direction": selected_topic.tentative_thesis_direction,
            },
            "max_notes": max_notes,
            "retrieved_chunks": [
                {
                    "source_id": chunk.source_id,
                    "chunk_id": chunk.chunk_id,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "text": chunk.text,
                }
                for chunk in chunks
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _result_from_payload(
    *,
    job: EssayJob,
    selected_topic: SelectedTopic,
    chunks: list[TopicEvidenceChunk],
    payload: dict[str, Any],
    evidence_map_version: int,
    prompt_version: str,
    max_notes: int,
) -> FinalTopicResearchResult:
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    warnings = _payload_list(payload, "warnings", max_items=20)
    notes: list[ResearchNote] = []

    for idx, item in enumerate(payload.get("notes", [])[:max_notes], start=1):
        chunk_id = str(item.get("chunk_id", "")).strip()
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            warnings.append(f"Dropped note with unknown chunk_id: {chunk_id}")
            continue
        note = _note_from_payload(
            item,
            note_id=f"note_{len(notes) + 1:03d}",
            chunk=chunk,
            warnings=warnings,
        )
        if note is not None:
            notes.append(note)

    note_ids = {note.id for note in notes}
    groups: list[EvidenceGroup] = []
    for idx, item in enumerate(payload.get("evidence_groups", []), start=1):
        requested_ids = _payload_list(item, "note_ids", max_items=50)
        valid_ids = [note_id for note_id in requested_ids if note_id in note_ids]
        missing_ids = [note_id for note_id in requested_ids if note_id not in note_ids]
        if missing_ids:
            warnings.append(f"Dropped unknown note ids from evidence group {idx}: {', '.join(missing_ids)}")
        if not valid_ids:
            continue
        groups.append(
            EvidenceGroup(
                id=f"group_{len(groups) + 1:03d}",
                label=str(item.get("label", "")).strip() or f"Evidence group {idx}",
                purpose=_coerce_group_purpose(item.get("purpose")),
                note_ids=valid_ids,
                synthesis=str(item.get("synthesis", "")).strip(),
            )
        )

    gaps = _payload_list(payload, "gaps", max_items=20)
    conflicts = _payload_list(payload, "conflicts", max_items=20)
    source_ids = sorted({note.source_id for note in notes})
    evidence_map = EvidenceMap(
        id=f"evidence_map_v{evidence_map_version:03d}",
        job_id=job.id,
        selected_topic_id=selected_topic.topic_id,
        research_question=selected_topic.research_question,
        thesis_direction=selected_topic.tentative_thesis_direction,
        notes=notes,
        evidence_groups=groups,
        gaps=gaps,
        conflicts=conflicts,
        source_ids=source_ids,
        prompt_version=prompt_version,
    )
    report = ResearchReport(
        job_id=job.id,
        selected_topic_id=selected_topic.topic_id,
        evidence_map_id=evidence_map.id,
        note_count=len(notes),
        source_count=len(source_ids),
        gaps=gaps,
        conflicts=conflicts,
        warnings=warnings,
    )
    return FinalTopicResearchResult(evidence_map=evidence_map, report=report)


def _note_from_payload(
    item: dict[str, Any],
    *,
    note_id: str,
    chunk: TopicEvidenceChunk,
    warnings: list[str],
) -> ResearchNote | None:
    quote = item.get("quote")
    quote_text = None if quote is None else str(quote).strip()
    if quote_text and quote_text not in chunk.text:
        warnings.append(f"Dropped quote for {note_id} because it was not found in chunk {chunk.chunk_id}.")
        quote_text = None
    page_start = int(item.get("page_start", chunk.page_start))
    page_end = int(item.get("page_end", chunk.page_end))
    if page_start != chunk.page_start or page_end != chunk.page_end:
        warnings.append(f"Corrected page range for {note_id} to match chunk {chunk.chunk_id}.")
        page_start = chunk.page_start
        page_end = chunk.page_end
    claim = str(item.get("claim", "")).strip()
    paraphrase = str(item.get("paraphrase", "")).strip()
    relevance = str(item.get("relevance", "")).strip()
    if not claim or not paraphrase or not relevance:
        warnings.append(f"Dropped incomplete note for chunk {chunk.chunk_id}.")
        return None
    return ResearchNote(
        id=note_id,
        source_id=chunk.source_id,
        chunk_id=chunk.chunk_id,
        page_start=page_start,
        page_end=page_end,
        claim=claim,
        quote=quote_text,
        paraphrase=paraphrase,
        relevance=relevance,
        supports_topic=bool(item.get("supports_topic", True)),
        evidence_type=_coerce_evidence_type(item.get("evidence_type")),
        tags=_payload_list(item, "tags", max_items=12),
        confidence=_bounded_float(item.get("confidence", 0.0)),
    )


def _flatten_chunks(topic_id: str, retrieved_evidence: list[RetrievedTopicEvidence]) -> list[TopicEvidenceChunk]:
    chunks: list[TopicEvidenceChunk] = []
    seen: set[str] = set()
    for evidence in retrieved_evidence:
        if evidence.topic_id != topic_id:
            continue
        for chunk in evidence.chunks:
            if chunk.chunk_id in seen:
                continue
            chunks.append(chunk)
            seen.add(chunk.chunk_id)
    return chunks


def _packet_chunks(source_packets: list[SourceTextPacket]) -> list[TopicEvidenceChunk]:
    chunks: list[TopicEvidenceChunk] = []
    for packet in source_packets:
        if not packet.text.strip():
            continue
        chunks.append(
            TopicEvidenceChunk(
                source_id=packet.source_id,
                chunk_id=packet.packet_id,
                page_start=packet.pdf_page_start or 1,
                page_end=packet.pdf_page_end or packet.pdf_page_start or 1,
                text=packet.text,
                score=None,
                retrieval_method=f"source_packet:{packet.locator.locator_type}",
            )
        )
    return chunks


def _empty_result(
    *,
    job: EssayJob,
    selected_topic: SelectedTopic,
    evidence_map_version: int,
    prompt_version: str,
    warning: str,
) -> FinalTopicResearchResult:
    evidence_map = EvidenceMap(
        id=f"evidence_map_v{evidence_map_version:03d}",
        job_id=job.id,
        selected_topic_id=selected_topic.topic_id,
        research_question=selected_topic.research_question,
        thesis_direction=selected_topic.tentative_thesis_direction,
        notes=[],
        evidence_groups=[],
        gaps=["No retrieved source evidence was available for this topic."],
        conflicts=[],
        source_ids=[],
        prompt_version=prompt_version,
    )
    report = ResearchReport(
        job_id=job.id,
        selected_topic_id=selected_topic.topic_id,
        evidence_map_id=evidence_map.id,
        note_count=0,
        source_count=0,
        gaps=evidence_map.gaps,
        conflicts=[],
        warnings=[warning],
    )
    return FinalTopicResearchResult(evidence_map=evidence_map, report=report)


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value[:max_items] if str(item).strip()]


def _bounded_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _coerce_evidence_type(value: Any) -> str:
    text = str(value or "other").strip().lower()
    allowed = {"background", "argument", "example", "counterargument", "statistic", "definition", "other"}
    return text if text in allowed else "other"


def _coerce_group_purpose(value: Any) -> str:
    text = str(value or "other").strip().lower()
    allowed = {"thesis_support", "background", "counterargument", "example", "limitation", "other"}
    return text if text in allowed else "other"
