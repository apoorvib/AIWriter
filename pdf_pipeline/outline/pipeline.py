"""End-to-end outline extraction orchestrator."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Mapping

from pypdf import PdfReader

from llm.client import LLMClient
from pdf_pipeline.ocr import OcrConfig, OcrTier
from pdf_pipeline.outline.anchor_scan import resolve_entries
from pdf_pipeline.outline.entry_extraction import (
    extract_toc_entries,
    extract_toc_entries_deterministic,
    RawEntry,
)
from pdf_pipeline.outline.label_resolve import resolve_entries_via_labels
from pdf_pipeline.outline.metadata import read_page_labels, read_pdf_outlines
from pdf_pipeline.outline.page_text import (
    DocumentOcrPageExtractor,
    LazyPageTextMap,
    LazyTesseractPageExtractor,
    PageTextSource,
    PyPdfPageExtractor,
)
from pdf_pipeline.outline.prefilter import looks_like_toc, select_toc_candidate_pages
from pdf_pipeline.outline.range_assignment import assign_end_pages
from pdf_pipeline.outline.schema import DocumentOutline

logger = logging.getLogger(__name__)

TocExtractionMode = Literal["auto", "deterministic", "llm"]
LLM_TOC_MAX_PAGES_PER_CHUNK = 1


def extract_outline(
    pdf_path: str | Path,
    llm_client: LLMClient,
    source_id: str,
    version: int = 1,
    max_toc_pages: int = 40,
    chunk_size: int = 5,
    max_offset: int = 100,
    ocr_tier: OcrTier | None = None,
    ocr_config: OcrConfig | None = None,
    llm_model: str | None = None,
    parallel_workers: int | str | None = None,
    calibrate: bool = False,
    toc_extraction_mode: TocExtractionMode = "auto",
    deterministic_min_entries: int = 10,
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

    # Shared text source: the same instance is used for the eager TOC scan and
    # (below) the lazy body-pages map, so per-page OCR results are cached once
    # and reused across both phases.
    source = _build_page_text_source(ocr_tier=ocr_tier, ocr_config=ocr_config)

    # Load text for the first max_toc_pages (capped at total_pages).
    scan_pages = min(max_toc_pages, total_pages)
    logger.info("Loading page text for pages 1..%d (TOC scan window)", scan_pages)
    pages_text = _load_pages_text(
        str(pdf_path),
        total_pages,
        scan_pages,
        source=source,
        ocr_tier=ocr_tier,
        ocr_config=ocr_config,
        parallel_workers=parallel_workers,
        calibrate=calibrate,
    )

    # Prefilter: is there a TOC to extract at all?
    combined = "\n".join(pages_text.get(p, "") for p in range(1, scan_pages + 1))
    if not looks_like_toc(combined):
        logger.info("Prefilter: no TOC-like text found; returning empty outline")
        return DocumentOutline(source_id=source_id, version=version, entries=[])
    candidate_pages = select_toc_candidate_pages(
        {p: pages_text.get(p, "") for p in range(1, scan_pages + 1)}
    )
    if candidate_pages:
        logger.info(
            "Prefilter: TOC-like text detected on candidate pages %s; running Layer 2",
            candidate_pages,
        )
    else:
        logger.info(
            "Prefilter: TOC-like text detected but no candidate window isolated; "
            "running Layer 2 over full scan window"
        )
        candidate_pages = list(range(1, scan_pages + 1))

    # Layer 2
    pages_payload = [
        {"pdf_page": p, "text": pages_text.get(p, "")} for p in candidate_pages
    ]
    effective_chunk_size = min(
        max(1, chunk_size),
        LLM_TOC_MAX_PAGES_PER_CHUNK,
        max(1, len(pages_payload)),
    )
    logger.info(
        "Layer 2 LLM chunk size: %d page(s) max per call", effective_chunk_size
    )
    raw = _extract_layer2_entries(
        pages_payload,
        llm_client=llm_client,
        chunk_size=effective_chunk_size,
        llm_model=llm_model,
        mode=toc_extraction_mode,
        deterministic_min_entries=deterministic_min_entries,
        allow_deterministic=ocr_tier is None,
    )
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
        logger.info("Layer 3: no /PageLabels; running anchor scan (lazy body-pages)")
        # Layer 3 - need body text over a wider range to locate anchors.
        # LazyPageTextMap only fetches pages the anchor scan actually probes,
        # so scanned PDFs don't pay OCR cost for the whole document.
        body_pages = _load_pages_text(
            str(pdf_path),
            total_pages,
            total_pages,
            source=source,
            lazy=True,
            ocr_tier=ocr_tier,
            ocr_config=ocr_config,
        )
        resolved = resolve_entries(
            raw, body_pages, max_offset=max_offset, total_pages=total_pages
        )
        matched = sum(1 for e in resolved if e.source == "anchor_scan")
        cached = getattr(body_pages, "cached_count", None)
        if cached is not None:
            logger.info(
                "Layer 3: %d/%d entries resolved via anchor scan "
                "(body pages fetched: %d/%d)",
                matched, len(resolved), cached, total_pages,
            )
        else:
            logger.info(
                "Layer 3: %d/%d entries resolved via anchor scan", matched, len(resolved)
            )

    finalized = assign_end_pages(resolved, total_pages=total_pages)
    logger.info("Layer 4: assigned end_pdf_page for %d entries", len(finalized))
    return DocumentOutline(source_id=source_id, version=version, entries=finalized)


def _extract_layer2_entries(
    pages_payload: list[dict],
    *,
    llm_client: LLMClient,
    chunk_size: int,
    llm_model: str | None,
    mode: TocExtractionMode,
    deterministic_min_entries: int,
    allow_deterministic: bool = True,
) -> list[RawEntry]:
    if mode not in ("auto", "deterministic", "llm"):
        raise ValueError(f"Unsupported TOC extraction mode: {mode!r}")
    if mode == "deterministic" and not allow_deterministic:
        raise ValueError(
            "Deterministic TOC extraction is disabled for OCR text. "
            "Use toc_extraction_mode='llm' for OCR, or omit ocr_tier for "
            "direct-PDF deterministic experiments."
        )

    deterministic: list[RawEntry] = []
    if mode == "auto" and not allow_deterministic:
        logger.info(
            "Layer 2: OCR text source detected; skipping deterministic parser "
            "and invoking LLM"
        )
    if mode == "deterministic" or (mode == "auto" and allow_deterministic):
        deterministic = extract_toc_entries_deterministic(pages_payload)
        logger.info(
            "Layer 2 deterministic: returned %d raw TOC entries",
            len(deterministic),
        )
        if mode == "deterministic":
            return deterministic
        if len(deterministic) >= deterministic_min_entries:
            logger.info(
                "Layer 2: using deterministic entries; skipping LLM "
                "(threshold=%d)",
                deterministic_min_entries,
            )
            return deterministic
        logger.info(
            "Layer 2: deterministic result below threshold=%d; invoking LLM",
            deterministic_min_entries,
        )

    raw = extract_toc_entries(
        pages_payload,
        llm_client,
        chunk_size=chunk_size,
        model=llm_model,
    )
    logger.info("Layer 2: LLM returned %d raw TOC entries", len(raw))
    if raw:
        return raw
    if deterministic:
        logger.info(
            "Layer 2 fallback: using %d deterministic raw TOC entries after empty LLM result",
            len(deterministic),
        )
    return deterministic


def _load_pages_text(
    pdf_path: str,
    total_pages: int,
    max_pages: int,
    *,
    source: PageTextSource | None = None,
    lazy: bool = False,
    ocr_tier: OcrTier | None = None,
    ocr_config: OcrConfig | None = None,
    parallel_workers: int | str | None = None,
    calibrate: bool = False,
) -> Mapping[int, str]:
    """Extract text for pages 1..max_pages. Overridable in tests.

    If `source` is not provided, builds one from `ocr_tier`/`ocr_config`.
    Reusing the same `source` across calls keeps the per-page OCR cache warm.

    If `lazy=True`, returns a LazyPageTextMap that fetches pages on demand
    (used for the anchor-scan body-pages phase, where only a small fraction
    of pages are typically probed). Otherwise returns an eager dict.

    If `parallel_workers` is set (and not lazy), delegates to `_parallel_ocr_pages`
    which runs `run_parallel_ocr` scoped to the TOC window using a temp store.
    """
    if parallel_workers is not None and not lazy:
        return _parallel_ocr_pages(
            pdf_path,
            total_pages,
            max_pages,
            ocr_tier=ocr_tier,
            ocr_config=ocr_config,
            parallel_workers=parallel_workers,
            calibrate=calibrate,
        )
    if source is None:
        source = _build_page_text_source(ocr_tier=ocr_tier, ocr_config=ocr_config)
    if lazy:
        return LazyPageTextMap(source, pdf_path, total_pages)
    upper = min(total_pages, max_pages)
    pages: dict[int, str] = {}
    for p in range(1, upper + 1):
        if p == 1 or p % 25 == 0 or p == upper:
            logger.info("  extracting text for page %d/%d", p, upper)
        pages[p] = source.get(pdf_path, p).text
    return pages


def _parallel_ocr_pages(
    pdf_path: str,
    total_pages: int,
    max_pages: int,
    *,
    ocr_tier: OcrTier | None,
    ocr_config: OcrConfig | None,
    parallel_workers: int | str,
    calibrate: bool,
) -> dict[int, str]:
    import shutil
    import tempfile

    import pdf_pipeline.ocr_parallel as par_mod
    from pdf_pipeline.ocr_parallel.schema import ParallelOcrConfig

    if ocr_tier is None:
        raise ValueError("parallel_workers requires ocr_tier to be set")
    if ocr_tier != OcrTier.SMALL:
        logger.info(
            "parallel_workers ignored for tier=%s (only Tesseract/small supports "
            "per-page parallelism); using sequential OCR",
            ocr_tier.value,
        )
        source = _build_page_text_source(ocr_tier=ocr_tier, ocr_config=ocr_config)
        upper = min(total_pages, max_pages)
        return {p: source.get(pdf_path, p).text for p in range(1, upper + 1)}

    config = ocr_config or OcrConfig()
    upper = min(total_pages, max_pages)
    tmp = tempfile.mkdtemp(prefix="outline_ocr_")
    try:
        par_config = ParallelOcrConfig(
            ocr_tier=ocr_tier,
            languages=config.languages,
            dpi=config.dpi,
            use_gpu=config.use_gpu,
            start_page=1,
            max_pages=upper,
            workers=parallel_workers,
            calibrate=calibrate,
            store_path=tmp,
        )
        logger.info(
            "Parallel OCR: fetching %d pages with workers=%s calibrate=%s",
            upper,
            parallel_workers,
            calibrate,
        )
        _, result = par_mod.run_parallel_ocr(pdf_path, config=par_config)
        return {p.page_number: p.text for p in result.pages}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _build_page_text_source(
    ocr_tier: OcrTier | None = None,
    ocr_config: OcrConfig | None = None,
) -> PageTextSource:
    ocr_extractor = _build_ocr_page_extractor(ocr_tier, ocr_config) if ocr_tier else None
    if ocr_extractor is not None:
        logger.info("  OCR fallback enabled (tier=%s)", ocr_tier.value)
    return PageTextSource(
        text_extractor=PyPdfPageExtractor(), ocr_extractor=ocr_extractor
    )


def _build_ocr_page_extractor(ocr_tier: OcrTier, ocr_config: OcrConfig | None):
    """Build a per-page OCR extractor appropriate for the tier.

    SMALL uses LazyTesseractPageExtractor: pages are rasterized + OCR'd one at
    a time and cached by (path, page). MEDIUM/HIGH still OCR the whole
    document up front via DocumentOcrPageExtractor (the underlying backends
    don't currently expose a per-page API).
    """
    config = ocr_config or OcrConfig()
    if ocr_tier == OcrTier.SMALL:
        return LazyTesseractPageExtractor(config=config)
    if ocr_tier == OcrTier.MEDIUM:
        from pdf_pipeline.extractors.easyocr_extractor import EasyOcrExtractor
        logger.info("  Medium OCR tier: whole-document OCR up front (not lazy)")
        return DocumentOcrPageExtractor(EasyOcrExtractor(config=config))
    if ocr_tier == OcrTier.HIGH:
        from pdf_pipeline.extractors.paddle_extractor import PaddleOcrExtractor
        logger.info("  High OCR tier: whole-document OCR up front (not lazy)")
        return DocumentOcrPageExtractor(PaddleOcrExtractor(config=config))
    raise ValueError(f"Unsupported OCR tier: {ocr_tier!r}")
