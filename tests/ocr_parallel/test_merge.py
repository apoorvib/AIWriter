from __future__ import annotations

from pdf_pipeline.ocr_parallel.merge import merge_page_results
from pdf_pipeline.ocr_parallel.schema import OcrPageResult


def _result(page_number: int, text: str, error: str | None = None) -> OcrPageResult:
    return OcrPageResult(
        document_id="doc1",
        source_path="book.pdf",
        page_number=page_number,
        text=text,
        char_count=len(text),
        extraction_method="ocr:tesseract",
        rasterization_ms=1.0,
        ocr_ms=2.0,
        normalization_ms=0.5,
        worker_pid=123,
        attempt=1,
        error_message=error,
    )


def test_merge_sorts_successful_pages_and_skips_failures() -> None:
    merged = merge_page_results(
        "book.pdf",
        page_count=3,
        results=[
            _result(3, "three"),
            _result(1, "one"),
            _result(2, "", error="failed"),
        ],
    )

    assert merged.page_count == 3
    assert [page.page_number for page in merged.pages] == [1, 3]
    assert [page.text for page in merged.pages] == ["one", "three"]
