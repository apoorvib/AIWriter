"""Per-page text source with text-extraction first and OCR fallback."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Protocol

from pypdf import PdfReader

from pdf_pipeline.ocr import OcrConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageTextRecord:
    pdf_page: int
    text: str
    used_ocr: bool


class _SinglePageExtractor(Protocol):
    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str: ...


class PageTextSource:
    """Returns the best available text for a given pdf_page.

    Prefers text extraction; falls back to OCR when extracted text is empty
    or shorter than `min_chars`. If both yield nothing, returns an empty
    PageTextRecord so callers can continue without branching on None.
    """

    def __init__(
        self,
        text_extractor: _SinglePageExtractor,
        ocr_extractor: _SinglePageExtractor | None,
        min_chars: int = 20,
    ) -> None:
        self._text = text_extractor
        self._ocr = ocr_extractor
        self._min_chars = min_chars

    def get(self, pdf_path: str, pdf_page: int) -> PageTextRecord:
        text = self._text.extract_page_text(pdf_path, pdf_page) or ""
        if len(text.strip()) >= self._min_chars:
            return PageTextRecord(pdf_page=pdf_page, text=text, used_ocr=False)
        if self._ocr is None:
            return PageTextRecord(pdf_page=pdf_page, text=text, used_ocr=False)
        ocr_text = self._ocr.extract_page_text(pdf_path, pdf_page) or ""
        return PageTextRecord(pdf_page=pdf_page, text=ocr_text, used_ocr=True)


class PyPdfPageExtractor:
    """Minimal per-page text extractor wrapping pypdf directly.

    Caches the most recently opened PdfReader by path so extracting many
    pages from the same file doesn't re-parse the xref table on each call.
    """

    def __init__(self) -> None:
        self._cached_path: str | None = None
        self._cached_reader: PdfReader | None = None

    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str:
        if pdf_path != self._cached_path or self._cached_reader is None:
            self._cached_reader = PdfReader(pdf_path)
            self._cached_path = pdf_path
        return self._cached_reader.pages[pdf_page - 1].extract_text() or ""


class DocumentOcrPageExtractor:
    """Adapts a whole-document OCR PdfExtractor to a per-page interface.

    Runs the underlying OCR extractor once per pdf_path and caches the
    per-page text. Callers pay one whole-document OCR pass up front, then
    page lookups are O(1).
    """

    def __init__(self, extractor) -> None:  # extractor: pdf_pipeline.extractors.base.PdfExtractor
        self._extractor = extractor
        self._cached_path: str | None = None
        self._cached_pages: dict[int, str] = {}

    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str:
        if pdf_path != self._cached_path:
            result = self._extractor.extract(pdf_path)
            self._cached_pages = {p.page_number: p.text for p in result.pages}
            self._cached_path = pdf_path
        return self._cached_pages.get(pdf_page, "")


class LazyTesseractPageExtractor:
    """Rasterize + OCR a single page on demand, caching the result.

    Unlike DocumentOcrPageExtractor which OCRs the whole PDF up front, this
    extractor rasterizes only the specific page requested via pypdfium2 and
    runs pytesseract on that image. Cache key is (pdf_path, pdf_page), so
    repeated access is free and unrelated pages never pay OCR cost.

    Use this in the outline pipeline where only a small fraction of pages
    are ever queried (TOC window + anchor-scan forward scans).
    """

    def __init__(self, config: OcrConfig | None = None) -> None:
        self._config = config or OcrConfig()
        self._cache: dict[tuple[str, int], str] = {}
        self._pdf_cache: dict[str, object] = {}

    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str:
        key = (pdf_path, pdf_page)
        if key in self._cache:
            return self._cache[key]
        try:
            import pypdfium2 as pdfium
            import pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "LazyTesseractPageExtractor requires pypdfium2 and pytesseract"
            ) from exc

        if pdf_path not in self._pdf_cache:
            self._pdf_cache[pdf_path] = pdfium.PdfDocument(pdf_path)
        pdf = self._pdf_cache[pdf_path]
        scale = self._config.dpi / 72.0
        lang = "+".join(_TESSERACT_LANG_ALIASES.get(l, l) for l in self._config.languages)
        image = pdf[pdf_page - 1].render(scale=scale).to_pil()
        text = pytesseract.image_to_string(image, lang=lang) or ""
        self._cache[key] = text
        return text


_TESSERACT_LANG_ALIASES = {"en": "eng"}


class LazyPageTextMap(Mapping[int, str]):
    """Dict-like page-text map that fetches (and caches) pages on demand.

    Implements just enough of the Mapping interface for anchor_scan:
    .get(key, default), .keys(), .__contains__, .__len__, iteration. Each
    .get() call that misses triggers one call into the underlying
    PageTextSource. Callers that only probe a handful of pages (e.g.
    anchor-scan forward scan, cross-validation) avoid materializing all
    total_pages entries up front.
    """

    def __init__(
        self,
        source: PageTextSource,
        pdf_path: str,
        total_pages: int,
    ) -> None:
        self._source = source
        self._pdf_path = pdf_path
        self._total_pages = total_pages
        self._cache: dict[int, str] = {}

    def _fetch(self, pdf_page: int) -> str:
        if pdf_page in self._cache:
            return self._cache[pdf_page]
        if pdf_page < 1 or pdf_page > self._total_pages:
            return ""
        text = self._source.get(self._pdf_path, pdf_page).text
        self._cache[pdf_page] = text
        return text

    def get(self, pdf_page: int, default: str = "") -> str:
        if pdf_page < 1 or pdf_page > self._total_pages:
            return default
        return self._fetch(pdf_page)

    def __getitem__(self, pdf_page: int) -> str:
        if pdf_page < 1 or pdf_page > self._total_pages:
            raise KeyError(pdf_page)
        return self._fetch(pdf_page)

    def __iter__(self):
        return iter(range(1, self._total_pages + 1))

    def __len__(self) -> int:
        return self._total_pages

    def __contains__(self, pdf_page) -> bool:
        try:
            p = int(pdf_page)
        except (ValueError, TypeError):
            return False
        return 1 <= p <= self._total_pages

    def keys(self):
        return range(1, self._total_pages + 1)

    @property
    def cached_count(self) -> int:
        return len(self._cache)
