from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pdf_pipeline.extractors.base import MissingDependencyError, OcrRuntimeError, PdfExtractor
from pdf_pipeline.extractors.ocr_common import iter_rasterized_pdf_pages
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.ocr import OcrConfig
from pdf_pipeline.text_utils import normalize_text


logger = logging.getLogger(__name__)

TESSERACT_LANGUAGE_ALIASES = {
    "en": "eng",
}


class TesseractOcrExtractor(PdfExtractor):
    def __init__(self, config: OcrConfig | None = None) -> None:
        self.config = config or OcrConfig()

    def extract(self, pdf_path: str | Path) -> DocumentExtractionResult:
        _require_pytesseract()
        lang = normalize_tesseract_languages(self.config.languages)
        pages: list[PageText] = []
        for page_number, image in iter_rasterized_pdf_pages(
            pdf_path,
            dpi=self.config.dpi,
            start_page=self.config.start_page,
            max_pages=self.config.max_pages,
        ):
            logger.info("Running Tesseract OCR on page %s", page_number)
            try:
                raw_text = tesseract_image_to_string(image, lang=lang)
            except Exception as exc:  # pragma: no cover - backend-specific runtime failures
                raise OcrRuntimeError(f"Tesseract OCR failed on page {page_number}") from exc
            text = normalize_text(raw_text or "")
            pages.append(PageText(page_number, text, len(text), "ocr:tesseract"))
        return DocumentExtractionResult(source_path=str(Path(pdf_path)), page_count=len(pages), pages=pages)


def normalize_tesseract_languages(languages: tuple[str, ...]) -> str:
    return "+".join(_normalize_tesseract_language(language) for language in languages)


def tesseract_image_to_string(image: Any, lang: str) -> str:
    pytesseract = _require_pytesseract()
    return pytesseract.image_to_string(image, lang=lang)


def _require_pytesseract():
    try:
        import pytesseract
    except ImportError as exc:
        raise MissingDependencyError(
            "Missing optional dependency 'pytesseract'. Install OCR small extras."
        ) from exc
    return pytesseract


def _normalize_tesseract_language(language: str) -> str:
    return TESSERACT_LANGUAGE_ALIASES.get(language, language)
