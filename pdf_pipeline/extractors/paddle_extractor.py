from __future__ import annotations

from pathlib import Path

from pdf_pipeline.extractors.base import MissingDependencyError, OcrRuntimeError, PdfExtractor
from pdf_pipeline.extractors.ocr_common import rasterize_pdf_pages
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.ocr import OcrConfig
from pdf_pipeline.text_utils import normalize_text


class PaddleOcrExtractor(PdfExtractor):
    def __init__(self, config: OcrConfig | None = None) -> None:
        self.config = config or OcrConfig()

    def extract(self, pdf_path: str | Path) -> DocumentExtractionResult:
        try:
            from paddleocr import PaddleOCR
            import numpy as np
        except ImportError as exc:
            raise MissingDependencyError("Missing optional dependency 'paddleocr'. Install OCR high extras.") from exc

        images = rasterize_pdf_pages(pdf_path, dpi=self.config.dpi)
        ocr = PaddleOCR(lang=self._primary_language(), use_gpu=self.config.use_gpu, ocr_version="PP-OCRv4")
        pages: list[PageText] = []
        for idx, image in enumerate(images, start=1):
            try:
                result = ocr.ocr(np.array(image), cls=True)
            except Exception as exc:  # pragma: no cover - backend-specific runtime failures
                raise OcrRuntimeError(f"PaddleOCR failed on page {idx}") from exc
            raw_text = _flatten_paddle_result(result)
            text = normalize_text(raw_text)
            pages.append(PageText(idx, text, len(text), "ocr:paddleocr"))
        return DocumentExtractionResult(source_path=str(Path(pdf_path)), page_count=len(pages), pages=pages)

    def _primary_language(self) -> str:
        if not self.config.languages:
            return "en"
        return self.config.languages[0]


def _flatten_paddle_result(result: list) -> str:
    lines: list[str] = []
    for page in result or []:
        for row in page or []:
            if len(row) < 2:
                continue
            text_info = row[1]
            if isinstance(text_info, (list, tuple)) and text_info:
                lines.append(str(text_info[0]))
    return "\n".join(lines)
