from __future__ import annotations

from pathlib import Path

from pdf_pipeline.extractors.base import MissingDependencyError, OcrRuntimeError, PdfExtractor
from pdf_pipeline.extractors.ocr_common import rasterize_pdf_pages
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.ocr import OcrConfig
from pdf_pipeline.text_utils import normalize_text


class EasyOcrExtractor(PdfExtractor):
    def __init__(self, config: OcrConfig | None = None) -> None:
        self.config = config or OcrConfig()

    def extract(self, pdf_path: str | Path) -> DocumentExtractionResult:
        try:
            import easyocr
            import numpy as np
        except ImportError as exc:
            raise MissingDependencyError("Missing optional dependency 'easyocr'. Install OCR medium extras.") from exc

        images = rasterize_pdf_pages(pdf_path, dpi=self.config.dpi)
        reader = easyocr.Reader(list(self.config.languages), gpu=self.config.use_gpu)
        pages: list[PageText] = []
        for idx, image in enumerate(images, start=1):
            try:
                lines = reader.readtext(np.array(image), detail=0, paragraph=True)
            except Exception as exc:  # pragma: no cover - backend-specific runtime failures
                raise OcrRuntimeError(f"EasyOCR failed on page {idx}") from exc
            raw_text = "\n".join(str(line) for line in lines)
            text = normalize_text(raw_text)
            pages.append(PageText(idx, text, len(text), "ocr:easyocr"))
        return DocumentExtractionResult(source_path=str(Path(pdf_path)), page_count=len(pages), pages=pages)
