from __future__ import annotations

import re

from essay_writer.sources.schema import SourceChunk, SourcePage


def chunk_pages(
    pages: list[SourcePage],
    *,
    source_id: str,
    target_chars: int = 3_000,
    overlap_chars: int = 300,
) -> list[SourceChunk]:
    if target_chars < 200:
        raise ValueError("target_chars must be >= 200")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")
    if overlap_chars >= target_chars:
        raise ValueError("overlap_chars must be smaller than target_chars")

    chunks: list[SourceChunk] = []
    current_parts: list[tuple[int, str]] = []
    current_chars = 0

    for page in pages:
        for segment in _page_segments(page.text, target_chars):
            segment_len = len(segment)
            if current_parts and current_chars + segment_len > target_chars:
                chunks.append(_make_chunk(source_id, len(chunks) + 1, current_parts))
                current_parts = _overlap_parts(current_parts, overlap_chars)
                current_chars = sum(len(text) for _, text in current_parts)
            current_parts.append((page.page_number, segment))
            current_chars += segment_len

    if current_parts:
        chunks.append(_make_chunk(source_id, len(chunks) + 1, current_parts))

    return chunks


def _page_segments(text: str, target_chars: int) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= target_chars:
        return [normalized]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    segments: list[str] = []
    for paragraph in paragraphs or [normalized]:
        if len(paragraph) <= target_chars:
            segments.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + target_chars)
            if end < len(paragraph):
                boundary = paragraph.rfind(" ", start, end)
                if boundary > start + target_chars // 2:
                    end = boundary
            segments.append(paragraph[start:end].strip())
            start = end
    return [segment for segment in segments if segment]


def _overlap_parts(parts: list[tuple[int, str]], overlap_chars: int) -> list[tuple[int, str]]:
    if overlap_chars == 0:
        return []
    kept: list[tuple[int, str]] = []
    total = 0
    for page_number, text in reversed(parts):
        if total >= overlap_chars:
            break
        if total + len(text) <= overlap_chars:
            kept.append((page_number, text))
            total += len(text)
            continue
        keep_len = overlap_chars - total
        kept.append((page_number, text[-keep_len:]))
        total += keep_len
    kept.reverse()
    return kept


def _make_chunk(source_id: str, ordinal: int, parts: list[tuple[int, str]]) -> SourceChunk:
    text = "\n\n".join(text for _, text in parts).strip()
    page_numbers = [page_number for page_number, _ in parts]
    return SourceChunk(
        id=f"{source_id}-chunk-{ordinal:04d}",
        source_id=source_id,
        ordinal=ordinal,
        page_start=min(page_numbers),
        page_end=max(page_numbers),
        text=text,
        char_count=len(text),
    )
