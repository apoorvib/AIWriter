from __future__ import annotations

from pathlib import Path

from pdf_pipeline.extractors.base import MissingDependencyError, OcrRuntimeError, PdfExtractor
from pdf_pipeline.extractors.ocr_common import rasterize_pdf_pages
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.ocr import OcrConfig
from pdf_pipeline.text_utils import normalize_text


class TesseractOcrExtractor(PdfExtractor):
    def __init__(self, config: OcrConfig | None = None) -> None:
        self.config = config or OcrConfig()

    def extract(self, pdf_path: str | Path) -> DocumentExtractionResult:
        try:
            import pytesseract
        except ImportError as exc:
            raise MissingDependencyError(
                "Missing optional dependency 'pytesseract'. Install OCR small extras."
            ) from exc

        images = rasterize_pdf_pages(pdf_path, dpi=self.config.dpi)
        lang = "+".join(self.config.languages)
        pages: list[PageText] = []
        for idx, image in enumerate(images, start=1):
            try:
                raw_text = pytesseract.image_to_string(image, lang=lang)
            except Exception as exc:  # pragma: no cover - backend-specific runtime failures
                raise OcrRuntimeError(f"Tesseract OCR failed on page {idx}") from exc
            text = normalize_text(raw_text or "")
            pages.append(PageText(idx, text, len(text), "ocr:tesseract"))
        return DocumentExtractionResult(source_path=str(Path(pdf_path)), page_count=len(pages), pages=pages)
