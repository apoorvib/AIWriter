from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pdf_pipeline.ocr import OcrTier


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceIngestionConfig:
    max_full_read_pages: int = 30
    max_full_read_chars: int = 120_000
    max_indexless_pages: int = 30
    max_indexless_chars: int = 120_000
    min_text_chars_per_page: int = 300
    min_readable_page_ratio: float = 0.7
    chunk_target_chars: int = 3_000
    chunk_overlap_chars: int = 300
    index_sources: bool = True
    require_index_for_large_sources: bool = True
    ocr_tier: OcrTier = OcrTier.SMALL
    source_card_input_char_budget: int = 16_000
    source_card_context_char_budget: int = 4_000
    source_card_summary_char_limit: int = 1_200

    def __post_init__(self) -> None:
        if self.max_full_read_pages < 1:
            raise ValueError("max_full_read_pages must be >= 1")
        if self.max_full_read_chars < 1:
            raise ValueError("max_full_read_chars must be >= 1")
        if self.max_indexless_pages < 1:
            raise ValueError("max_indexless_pages must be >= 1")
        if self.max_indexless_chars < 1:
            raise ValueError("max_indexless_chars must be >= 1")
        if self.min_text_chars_per_page < 0:
            raise ValueError("min_text_chars_per_page must be >= 0")
        if not 0.0 <= self.min_readable_page_ratio <= 1.0:
            raise ValueError("min_readable_page_ratio must be between 0.0 and 1.0")
        if self.chunk_target_chars < 200:
            raise ValueError("chunk_target_chars must be >= 200")
        if self.chunk_overlap_chars < 0:
            raise ValueError("chunk_overlap_chars must be >= 0")
        if self.chunk_overlap_chars >= self.chunk_target_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_target_chars")
        if self.source_card_input_char_budget < 1:
            raise ValueError("source_card_input_char_budget must be >= 1")
        if self.source_card_context_char_budget < 500:
            raise ValueError("source_card_context_char_budget must be >= 500")
        if self.source_card_summary_char_limit < 200:
            raise ValueError("source_card_summary_char_limit must be >= 200")


@dataclass(frozen=True)
class SourcePage:
    source_id: str
    page_number: int
    text: str
    char_count: int
    extraction_method: str


@dataclass(frozen=True)
class SourceChunk:
    id: str
    source_id: str
    ordinal: int
    page_start: int
    page_end: int
    text: str
    char_count: int


@dataclass(frozen=True)
class SourceDocument:
    id: str
    original_path: str
    file_name: str
    source_type: str
    page_count: int
    char_count: int
    extraction_method: str
    text_quality: str
    full_text_available: bool
    indexed: bool
    artifact_dir: str | None = None
    source_card_path: str | None = None
    index_path: str | None = None
    index_manifest_path: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class SourceCard:
    source_id: str
    title: str
    source_type: str
    page_count: int
    extraction_method: str
    brief_summary: str
    key_topics: list[str] = field(default_factory=list)
    useful_for_topic_ideation: list[str] = field(default_factory=list)
    notable_sections: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    citation_metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_context(self, max_chars: int = 4_000) -> str:
        parts = [
            f"Source: {self.title}",
            f"Source ID: {self.source_id}",
            f"Type: {self.source_type}; Pages: {self.page_count}; Extraction: {self.extraction_method}",
            f"Summary: {self.brief_summary}",
            _format_list("Key topics", self.key_topics),
            _format_list("Useful for topic ideation", self.useful_for_topic_ideation),
            _format_list("Notable sections", self.notable_sections),
            _format_list("Limitations", self.limitations),
        ]
        text = "\n".join(part for part in parts if part)
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."


@dataclass(frozen=True)
class SourceIngestionResult:
    source: SourceDocument
    pages: list[SourcePage]
    chunks: list[SourceChunk]
    source_card: SourceCard
    indexed: bool
    full_text_available: bool
    index_manifest: SourceIndexManifest | None = None
    warnings: list[str] = field(default_factory=list)


def artifact_path(root: str | Path, source_id: str, name: str) -> str:
    return str(Path(root) / source_id / name)


def _format_list(label: str, values: list[str]) -> str:
    if not values:
        return ""
    return f"{label}: " + "; ".join(values)


@dataclass(frozen=True)
class SourceIndexEntry:
    chunk_id: str
    ordinal: int
    page_start: int
    page_end: int
    char_count: int
    heading: str
    preview: str


@dataclass(frozen=True)
class SourceIndexManifest:
    source_id: str
    index_path: str
    total_chunks: int
    total_chars: int
    entries: list[SourceIndexEntry]
    created_at: str = field(default_factory=utc_now_iso)

    def to_context(self, *, max_preview_chars: int = 180) -> str:
        lines = [
            f"Source ID: {self.source_id}",
            f"Index handle: {self.source_id}",
            f"Chunks: {self.total_chunks}; Indexed chars: {self.total_chars}",
            "Complete chunk index:",
        ]
        for entry in self.entries:
            preview = entry.preview
            if len(preview) > max_preview_chars:
                preview = preview[: max_preview_chars - 3].rstrip() + "..."
            page_range = str(entry.page_start)
            if entry.page_end != entry.page_start:
                page_range = f"{entry.page_start}-{entry.page_end}"
            lines.append(
                f"- {entry.chunk_id} | pages {page_range} | {entry.char_count} chars | "
                f"{entry.heading}: {preview}"
            )
        return "\n".join(lines)
