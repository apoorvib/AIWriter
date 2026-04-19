from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from llm.client import LLMClient
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
    if llm_client is not None:
        payload = llm_client.chat_json(
            system=SOURCE_CARD_SYSTEM_PROMPT,
            user=_build_source_card_user_message(source, excerpts, summary_char_limit),
            json_schema=SOURCE_CARD_SCHEMA,
            max_tokens=2500,
        )
        return _card_from_payload(source, payload, summary_char_limit)
    return _deterministic_source_card(source, chunks, excerpts, summary_char_limit)


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


def _deterministic_source_card(
    source: SourceDocument,
    chunks: list[SourceChunk],
    excerpts: list[SourceChunk],
    summary_char_limit: int,
) -> SourceCard:
    excerpt_text = "\n\n".join(chunk.text for chunk in excerpts).strip()
    title = _infer_title(source, excerpt_text)
    summary = _compact_summary(excerpt_text, summary_char_limit)
    topics = _extract_key_topics(" ".join(chunk.text for chunk in chunks), limit=10)
    notable = [
        f"Pages {chunk.page_start}-{chunk.page_end}: {_first_sentence(chunk.text, 180)}"
        for chunk in excerpts[:5]
    ]
    return SourceCard(
        source_id=source.id,
        title=title,
        source_type=source.source_type,
        page_count=source.page_count,
        extraction_method=source.extraction_method,
        brief_summary=summary,
        key_topics=topics,
        useful_for_topic_ideation=[
            f"Use the indexed chunks to search this source for: {topic}"
            for topic in topics[:5]
        ],
        notable_sections=notable,
        limitations=[
            "LLM source-card summarization was not run; this card is based on deterministic excerpts and term extraction."
        ],
        citation_metadata={"file_name": source.file_name},
        warnings=[],
    )


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


def _infer_title(source: SourceDocument, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if 8 <= len(stripped) <= 160:
            return stripped
    return Path(source.file_name).stem


def _compact_summary(text: str, limit: int) -> str:
    if not text:
        return "No readable source text was available for summary generation."
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    summary = " ".join(sentence for sentence in sentences if sentence)[:limit].strip()
    if len(summary) == limit:
        summary = summary[: max(0, limit - 3)].rstrip() + "..."
    return summary


def _first_sentence(text: str, limit: int) -> str:
    return _compact_summary(text, limit)


def _extract_key_topics(text: str, *, limit: int) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    counts = Counter(word for word in words if word not in _STOPWORDS)
    return [word for word, _ in counts.most_common(limit)]


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


_STOPWORDS = {
    "about",
    "after",
    "also",
    "because",
    "been",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "most",
    "only",
    "other",
    "over",
    "such",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "were",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}
