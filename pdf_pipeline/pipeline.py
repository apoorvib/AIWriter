from __future__ import annotations

from pathlib import Path

from pdf_pipeline.extractors.base import PdfExtractor
from pdf_pipeline.extractors.easyocr_extractor import EasyOcrExtractor
from pdf_pipeline.extractors.paddle_extractor import PaddleOcrExtractor
from pdf_pipeline.extractors.pypdf_extractor import PyPdfExtractor
from pdf_pipeline.extractors.tesseract_extractor import TesseractOcrExtractor
from pdf_pipeline.models import DocumentExtractionResult
from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig, OcrTier


class ExtractionPipeline:
    def __init__(
        self,
        mode: ExtractionMode = ExtractionMode.TEXT_ONLY,
        ocr_tier: OcrTier = OcrTier.SMALL,
        ocr_config: OcrConfig | None = None,
    ) -> None:
        self.mode = mode
        self.ocr_tier = ocr_tier
        self.ocr_config = ocr_config or OcrConfig()

    def extract(self, pdf_path: str | Path) -> DocumentExtractionResult:
        if self.mode == ExtractionMode.AUTO:
            raise NotImplementedError("ExtractionMode.AUTO is not implemented yet.")
        return self._resolve_extractor().extract(pdf_path)

    def _resolve_extractor(self) -> PdfExtractor:
        if self.mode == ExtractionMode.TEXT_ONLY:
            return PyPdfExtractor()
        if self.mode == ExtractionMode.OCR_ONLY:
            if self.ocr_tier == OcrTier.SMALL:
                return TesseractOcrExtractor(config=self.ocr_config)
            if self.ocr_tier == OcrTier.MEDIUM:
                return EasyOcrExtractor(config=self.ocr_config)
            if self.ocr_tier == OcrTier.HIGH:
                return PaddleOcrExtractor(config=self.ocr_config)
            raise ValueError(f"Unsupported OCR tier: {self.ocr_tier}")
        raise ValueError(f"Unsupported extraction mode: {self.mode}")
