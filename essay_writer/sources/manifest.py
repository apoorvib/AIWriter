from __future__ import annotations

import re

from essay_writer.sources.schema import SourceChunk, SourceIndexEntry, SourceIndexManifest


def build_index_manifest(
    *,
    source_id: str,
    index_path: str,
    chunks: list[SourceChunk],
    preview_chars: int = 240,
) -> SourceIndexManifest:
    if preview_chars < 80:
        raise ValueError("preview_chars must be >= 80")
    entries = [
        SourceIndexEntry(
            chunk_id=chunk.id,
            ordinal=chunk.ordinal,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            char_count=chunk.char_count,
            heading=_extract_heading(chunk.text),
            preview=_preview(chunk.text, preview_chars),
        )
        for chunk in chunks
    ]
    return SourceIndexManifest(
        source_id=source_id,
        index_path=index_path,
        total_chunks=len(chunks),
        total_chars=sum(chunk.char_count for chunk in chunks),
        entries=entries,
    )


def _extract_heading(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:12]:
        if len(line) <= 120 and _looks_heading_like(line):
            return line
    for line in lines:
        cleaned = _clean_inline(line)
        if cleaned:
            return cleaned[:120]
    return "Untitled chunk"


def _looks_heading_like(line: str) -> bool:
    return bool(
        line.isupper()
        or line.istitle()
        or re.match(r"^(chapter|section|part|article|introduction|conclusion|abstract|discussion)\b", line, re.I)
        or re.match(r"^\d+(\.\d+)*[\).]?\s+\w+", line)
    )


def _preview(text: str, max_chars: int) -> str:
    cleaned = _clean_inline(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _clean_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
