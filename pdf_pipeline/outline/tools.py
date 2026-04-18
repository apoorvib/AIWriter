"""Tool surface: list_outline, get_section."""
from __future__ import annotations

from typing import Protocol

from pdf_pipeline.outline.page_text import PyPdfPageExtractor
from pdf_pipeline.outline.schema import OutlineEntry
from pdf_pipeline.outline.storage import OutlineStore


class SectionLookupError(Exception):
    """Raised when get_section cannot return text for the requested entry."""


class _PageExtractor(Protocol):
    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str: ...


def list_outline(source_id: str, store: OutlineStore) -> list[OutlineEntry]:
    return store.load_latest(source_id).entries


def get_section(
    source_id: str,
    entry_id: str,
    pdf_path: str,
    store: OutlineStore,
    extractor: _PageExtractor | None = None,
) -> str:
    outline = store.load_latest(source_id)
    for e in outline.entries:
        if e.id == entry_id:
            if e.start_pdf_page is None or e.end_pdf_page is None:
                raise SectionLookupError(f"entry {entry_id!r} is unresolved (no pdf_page range)")
            ext = extractor or PyPdfPageExtractor()
            pages = [
                ext.extract_page_text(pdf_path, p)
                for p in range(e.start_pdf_page, e.end_pdf_page + 1)
            ]
            return "\n".join(pages)
    raise SectionLookupError(f"entry_id not found: {entry_id!r}")
