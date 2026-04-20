from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from llm.client import LLMClient, LLMConfigurationError
from essay_writer.sources.schema import SourceCard, SourceChunk, SourceDocument


SOURCE_CARD_SYSTEM_PROMPT = """You create compact source cards for an essay-planning system.

Use only the provided uploaded-source excerpts. Do not use web knowledge.
Keep the card moderately detailed but concise enough to pass into topic ideation.
If metadata is missing, leave it blank or mention the limitation.
"""


SOURCE_CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "brief_summary",
        "key_topics",
        "useful_for_topic_ideation",
        "notable_sections",
        "limitations",
        "citation_metadata",
        "warnings",
    ],
    "properties": {
        "title": {"type": "string"},
        "brief_summary": {"type": "string"},
        "key_topics": {"type": "array", "items": {"type": "string"}},
        "useful_for_topic_ideation": {"type": "array", "items": {"type": "string"}},
        "notable_sections": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "citation_metadata": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def build_source_card(
    source: SourceDocument,
    chunks: list[SourceChunk],
    *,
    llm_client: LLMClient | None = None,
    input_char_budget: int = 16_000,
    summary_char_limit: int = 1_200,
) -> SourceCard:
    excerpts = select_source_card_excerpts(chunks, char_budget=input_char_budget)
    if llm_client is None:
        raise LLMConfigurationError("Source card generation requires an LLM client.")
    payload = llm_client.chat_json(
        system=SOURCE_CARD_SYSTEM_PROMPT,
        user=_build_source_card_user_message(source, excerpts, summary_char_limit),
        json_schema=SOURCE_CARD_SCHEMA,
        max_tokens=2500,
    )
    return _card_from_payload(source, payload, summary_char_limit)


def select_source_card_excerpts(chunks: list[SourceChunk], *, char_budget: int) -> list[SourceChunk]:
    if char_budget < 1:
        raise ValueError("char_budget must be >= 1")
    if not chunks:
        return []

    selected: list[SourceChunk] = []
    seen: set[str] = set()

    candidate_positions = [0, 1, len(chunks) // 2, len(chunks) - 2, len(chunks) - 1]
    for idx in candidate_positions:
        if 0 <= idx < len(chunks):
            _append_if_budget(selected, seen, chunks[idx], char_budget)

    for chunk in chunks:
        if _looks_section_dense(chunk.text):
            _append_if_budget(selected, seen, chunk, char_budget)
        if sum(item.char_count for item in selected) >= char_budget:
            break

    if not selected:
        _append_if_budget(selected, seen, chunks[0], char_budget)
    return sorted(selected, key=lambda item: item.ordinal)


def _card_from_payload(source: SourceDocument, payload: dict[str, Any], summary_char_limit: int) -> SourceCard:
    summary = str(payload.get("brief_summary", "")).strip()
    if len(summary) > summary_char_limit:
        summary = summary[: summary_char_limit - 3].rstrip() + "..."
    return SourceCard(
        source_id=source.id,
        title=str(payload.get("title") or Path(source.file_name).stem),
        source_type=source.source_type,
        page_count=source.page_count,
        extraction_method=source.extraction_method,
        brief_summary=summary,
        key_topics=_payload_list(payload, "key_topics", max_items=12, max_chars=120),
        useful_for_topic_ideation=_payload_list(payload, "useful_for_topic_ideation", max_items=8, max_chars=180),
        notable_sections=_payload_list(payload, "notable_sections", max_items=8, max_chars=180),
        limitations=_payload_list(payload, "limitations", max_items=8, max_chars=180),
        citation_metadata={str(key): str(value) for key, value in dict(payload.get("citation_metadata", {})).items()},
        warnings=_payload_list(payload, "warnings", max_items=8, max_chars=180),
    )


def _build_source_card_user_message(
    source: SourceDocument,
    excerpts: list[SourceChunk],
    summary_char_limit: int,
) -> str:
    return json.dumps(
        {
            "source": {
                "source_id": source.id,
                "file_name": source.file_name,
                "source_type": source.source_type,
                "page_count": source.page_count,
                "extraction_method": source.extraction_method,
            },
            "summary_char_limit": summary_char_limit,
            "excerpts": [
                {
                    "chunk_id": chunk.id,
                    "pages": [chunk.page_start, chunk.page_end],
                    "text": chunk.text,
                }
                for chunk in excerpts
            ],
        },
        ensure_ascii=False,
    )


def _append_if_budget(
    selected: list[SourceChunk],
    seen: set[str],
    chunk: SourceChunk,
    char_budget: int,
) -> None:
    if chunk.id in seen:
        return
    current = sum(item.char_count for item in selected)
    if selected and current + chunk.char_count > char_budget:
        return
    selected.append(chunk)
    seen.add(chunk.id)


def _looks_section_dense(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    heading_like = 0
    for line in lines[:20]:
        if len(line) <= 80 and (line.istitle() or line.isupper() or re.match(r"^\d+(\.\d+)*\s+\w+", line)):
            heading_like += 1
    return heading_like >= 2


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int, max_chars: int) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        value = [value]
    result = []
    for item in value[:max_items]:
        text = str(item).strip()
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        if text:
            result.append(text)
    return result
