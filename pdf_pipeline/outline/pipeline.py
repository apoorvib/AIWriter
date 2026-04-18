"""End-to-end outline extraction orchestrator."""
from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader

from llm.client import LLMClient
from pdf_pipeline.outline.anchor_scan import resolve_entries
from pdf_pipeline.outline.entry_extraction import extract_toc_entries
from pdf_pipeline.outline.label_resolve import resolve_entries_via_labels
from pdf_pipeline.outline.metadata import read_page_labels, read_pdf_outlines
from pdf_pipeline.outline.page_text import PageTextSource, PyPdfPageExtractor
from pdf_pipeline.outline.prefilter import looks_like_toc
from pdf_pipeline.outline.range_assignment import assign_end_pages
from pdf_pipeline.outline.schema import DocumentOutline

logger = logging.getLogger(__name__)


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
    are used directly. Otherwise Layer 2 extracts TOC entries via the LLM;
    if /PageLabels is present (Layer 1.5) the printed_page of each entry is
    resolved directly against the label map, skipping the anchor scan.
    Otherwise Layer 3 resolves pdf_pages via anchor scan. Layer 4 assigns
    end pages.
    """
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    logger.info("extract_outline: source_id=%s total_pages=%d", source_id, total_pages)

    # Layer 1
    pdf_outline = read_pdf_outlines(pdf_path)
    if pdf_outline:
        logger.info("Layer 1 hit: /Outlines yielded %d entries", len(pdf_outline))
        finalized = assign_end_pages(pdf_outline, total_pages=total_pages)
        return DocumentOutline(source_id=source_id, version=version, entries=finalized)
    logger.info("Layer 1 miss: no /Outlines; falling through to TOC extraction")

    # Load text for the first max_toc_pages (capped at total_pages).
    scan_pages = min(max_toc_pages, total_pages)
    logger.info("Loading page text for pages 1..%d (TOC scan window)", scan_pages)
    pages_text = _load_pages_text(str(pdf_path), total_pages, scan_pages)

    # Prefilter: is there a TOC to extract at all?
    combined = "\n".join(pages_text.get(p, "") for p in range(1, scan_pages + 1))
    if not looks_like_toc(combined):
        logger.info("Prefilter: no TOC-like text found; returning empty outline")
        return DocumentOutline(source_id=source_id, version=version, entries=[])
    logger.info("Prefilter: TOC-like text detected; invoking LLM (Layer 2)")

    # Layer 2
    pages_payload = [
        {"pdf_page": p, "text": pages_text.get(p, "")} for p in range(1, scan_pages + 1)
    ]
    raw = extract_toc_entries(pages_payload, llm_client, chunk_size=chunk_size)
    logger.info("Layer 2: LLM returned %d raw TOC entries", len(raw))
    if not raw:
        return DocumentOutline(source_id=source_id, version=version, entries=[])

    # Layer 1.5 - if /PageLabels is present, resolve directly against it.
    labels = read_page_labels(pdf_path)
    if labels is not None:
        logger.info(
            "Layer 1.5: /PageLabels present (%d labels); resolving directly", len(labels)
        )
        resolved = resolve_entries_via_labels(raw, labels)
        matched = sum(1 for e in resolved if e.source == "page_labels")
        logger.info(
            "Layer 1.5: %d/%d entries matched via page labels", matched, len(resolved)
        )
    else:
        logger.info("Layer 3: no /PageLabels; running anchor scan")
        # Layer 3 - need body text over a wider range to locate anchors.
        body_pages = _load_pages_text(str(pdf_path), total_pages, total_pages)
        resolved = resolve_entries(
            raw, body_pages, max_offset=max_offset, total_pages=total_pages
        )
        matched = sum(1 for e in resolved if e.source == "anchor_scan")
        logger.info(
            "Layer 3: %d/%d entries resolved via anchor scan", matched, len(resolved)
        )

    finalized = assign_end_pages(resolved, total_pages=total_pages)
    logger.info("Layer 4: assigned end_pdf_page for %d entries", len(finalized))
    return DocumentOutline(source_id=source_id, version=version, entries=finalized)


def _load_pages_text(pdf_path: str, total_pages: int, max_pages: int) -> dict[int, str]:
    """Extract text for pages 1..max_pages. Overridable in tests."""
    source = PageTextSource(text_extractor=PyPdfPageExtractor(), ocr_extractor=None)
    upper = min(total_pages, max_pages)
    pages: dict[int, str] = {}
    for p in range(1, upper + 1):
        if p == 1 or p % 25 == 0 or p == upper:
            logger.info("  extracting text for page %d/%d", p, upper)
        pages[p] = source.get(pdf_path, p).text
    return pages
