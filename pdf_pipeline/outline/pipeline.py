"""End-to-end outline extraction orchestrator."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from llm.client import LLMClient
from pdf_pipeline.outline.anchor_scan import resolve_entries
from pdf_pipeline.outline.entry_extraction import extract_toc_entries
from pdf_pipeline.outline.metadata import read_page_labels, read_pdf_outlines
from pdf_pipeline.outline.page_text import PageTextSource, PyPdfPageExtractor
from pdf_pipeline.outline.prefilter import looks_like_toc
from pdf_pipeline.outline.range_assignment import assign_end_pages
from pdf_pipeline.outline.schema import DocumentOutline


def extract_outline(
    pdf_path: str | Path,
    llm_client: LLMClient,
    source_id: str,
    version: int = 1,
    max_toc_pages: int = 40,
    chunk_size: int = 5,
    max_offset: int = 100,
) -> DocumentOutline:
    """Extract a DocumentOutline from `pdf_path`.

    Layer 1 (structural metadata) is tried first. If it yields entries, they
    are used directly. Otherwise Layer 2 extracts TOC entries via the LLM,
    and Layer 3 resolves pdf_pages via anchor scan. Layer 4 assigns end
    pages.
    """
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)

    # Layer 1
    pdf_outline = read_pdf_outlines(pdf_path)
    if pdf_outline:
        finalized = assign_end_pages(pdf_outline, total_pages=total_pages)
        return DocumentOutline(source_id=source_id, version=version, entries=finalized)

    # Load text for the first max_toc_pages (capped at total_pages).
    scan_pages = min(max_toc_pages, total_pages)
    pages_text = _load_pages_text(str(pdf_path), total_pages, scan_pages)

    # Prefilter: is there a TOC to extract at all?
    combined = "\n".join(pages_text.get(p, "") for p in range(1, scan_pages + 1))
    if not looks_like_toc(combined):
        return DocumentOutline(source_id=source_id, version=version, entries=[])

    # Layer 2
    pages_payload = [
        {"pdf_page": p, "text": pages_text.get(p, "")} for p in range(1, scan_pages + 1)
    ]
    raw = extract_toc_entries(pages_payload, llm_client, chunk_size=chunk_size)
    if not raw:
        return DocumentOutline(source_id=source_id, version=version, entries=[])

    # Layer 3 - need body text over a wider range to locate anchors.
    body_pages = _load_pages_text(str(pdf_path), total_pages, total_pages)
    resolved = resolve_entries(
        raw, body_pages, max_offset=max_offset, total_pages=total_pages
    )

    # Optional: use /PageLabels to backfill printed_page sanity (future work).
    _ = read_page_labels(pdf_path)

    finalized = assign_end_pages(resolved, total_pages=total_pages)
    return DocumentOutline(source_id=source_id, version=version, entries=finalized)


def _load_pages_text(pdf_path: str, total_pages: int, max_pages: int) -> dict[int, str]:
    """Extract text for pages 1..max_pages. Overridable in tests."""
    source = PageTextSource(text_extractor=PyPdfPageExtractor(), ocr_extractor=None)
    return {
        p: source.get(pdf_path, p).text for p in range(1, min(total_pages, max_pages) + 1)
    }
