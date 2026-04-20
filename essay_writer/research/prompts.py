from __future__ import annotations

from typing import Any


FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT = """You extract source-grounded research notes for an essay workflow.

Use only the supplied selected topic, task specification, and retrieved source chunks.
Do not invent sources, quotes, page numbers, authors, or facts.
Every note must cite source_id, chunk_id, and page range from the supplied chunks.
Quotes must be exact text copied from the supplied chunk. If no exact quote is useful, set quote to null.
Separate support, background, examples, counterarguments, statistics, definitions, and limitations.
If evidence is weak or missing, report gaps instead of fabricating support.
Return structured JSON only.
"""


FINAL_TOPIC_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notes", "evidence_groups", "gaps", "conflicts", "warnings"],
    "properties": {
        "gaps": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_id",
                    "chunk_id",
                    "page_start",
                    "page_end",
                    "claim",
                    "quote",
                    "paraphrase",
                    "relevance",
                    "supports_topic",
                    "evidence_type",
                    "tags",
                    "confidence",
                ],
                "properties": {
                    "source_id": {"type": "string"},
                    "chunk_id": {"type": "string"},
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
                    "claim": {"type": "string"},
                    "quote": {"type": ["string", "null"]},
                    "paraphrase": {"type": "string"},
                    "relevance": {"type": "string"},
                    "supports_topic": {"type": "boolean"},
                    "evidence_type": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
            },
        },
        "evidence_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "purpose", "note_ids", "synthesis"],
                "properties": {
                    "label": {"type": "string"},
                    "purpose": {"type": "string"},
                    "note_ids": {"type": "array", "items": {"type": "string"}},
                    "synthesis": {"type": "string"},
                },
            },
        },
    },
}
