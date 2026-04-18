from __future__ import annotations

from pdf_pipeline.models import DocumentExtractionResult
from pdf_pipeline.ocr_parallel.page_worker import page_result_to_page_text
from pdf_pipeline.ocr_parallel.schema import OcrPageResult


def merge_page_results(
    source_path: str,
    page_count: int,
    results: list[OcrPageResult],
) -> DocumentExtractionResult:
    successful = sorted(
        (result for result in results if result.succeeded),
        key=lambda result: result.page_number,
    )
    return DocumentExtractionResult(
        source_path=source_path,
        page_count=page_count,
        pages=[page_result_to_page_text(result) for result in successful],
    )
