"""Per-page text source with text-extraction first and OCR fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pypdf import PdfReader


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
    """Minimal per-page text extractor wrapping pypdf directly."""

    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str:
        reader = PdfReader(pdf_path)
        return reader.pages[pdf_page - 1].extract_text() or ""
