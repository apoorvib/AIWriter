from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pdf_pipeline.models import DocumentExtractionResult
from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig, OcrTier
from pdf_pipeline.ocr_parallel.page_worker import run_page_ocr_task
from pdf_pipeline.ocr_parallel.schema import OcrPageTask
from pdf_pipeline.pipeline import ExtractionPipeline
from essay_writer.sources.schema import SourcePage


class PdfPageOcrProvider(Protocol):
    def extract_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
        *,
        source_id: str,
    ) -> list[SourcePage]: ...


class DefaultPdfPageOcrProvider:
    def __init__(
        self,
        *,
        ocr_tier: OcrTier = OcrTier.SMALL,
        dpi: int = 300,
        languages: tuple[str, ...] = ("en",),
        use_gpu: bool = False,
    ) -> None:
        self._ocr_tier = ocr_tier
        self._dpi = dpi
        self._languages = languages
        self._use_gpu = use_gpu

    def extract_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
        *,
        source_id: str,
    ) -> list[SourcePage]:
        if self._ocr_tier == OcrTier.SMALL:
            return self._extract_small_pages(pdf_path, page_numbers, source_id=source_id)
        return self._extract_sequential_pages(pdf_path, page_numbers, source_id=source_id)

    def _extract_small_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
        *,
        source_id: str,
    ) -> list[SourcePage]:
        pages: list[SourcePage] = []
        for page_number in page_numbers:
            result = run_page_ocr_task(
                OcrPageTask(
                    document_id=source_id,
                    source_path=str(pdf_path),
                    page_number=page_number,
                    ocr_tier=self._ocr_tier,
                    dpi=self._dpi,
                    languages=self._languages,
                    use_gpu=self._use_gpu,
                )
            )
            if result.succeeded:
                pages.append(
                    SourcePage(
                        source_id=source_id,
                        page_number=result.page_number,
                        text=result.text,
                        char_count=result.char_count,
                        extraction_method=result.extraction_method,
                    )
                )
        return pages

    def _extract_sequential_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
        *,
        source_id: str,
    ) -> list[SourcePage]:
        pages: list[SourcePage] = []
        for page_number in page_numbers:
            result = ExtractionPipeline(
                mode=ExtractionMode.OCR_ONLY,
                ocr_tier=self._ocr_tier,
                ocr_config=OcrConfig(
                    languages=self._languages,
                    dpi=self._dpi,
                    use_gpu=self._use_gpu,
                    start_page=page_number,
                    max_pages=1,
                ),
            ).extract(pdf_path)
            pages.extend(_source_pages(source_id, result))
        return sorted(pages, key=lambda item: item.page_number)


def _source_pages(source_id: str, result: DocumentExtractionResult) -> list[SourcePage]:
    return [
        SourcePage(
            source_id=source_id,
            page_number=page.page_number,
            text=page.text,
            char_count=page.char_count,
            extraction_method=page.extraction_method,
        )
        for page in result.pages
    ]
