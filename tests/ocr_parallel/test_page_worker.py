from __future__ import annotations

from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.page_worker import run_page_ocr_task
from pdf_pipeline.ocr_parallel.schema import OcrPageTask


def test_tesseract_page_worker_returns_page_result(monkeypatch) -> None:
    import pdf_pipeline.ocr_parallel.page_worker as module

    monkeypatch.setattr(module, "render_pdf_page", lambda path, page_number, dpi: object())
    monkeypatch.setattr(module, "tesseract_image_to_string", lambda image, lang: f"text for {lang}")

    result = run_page_ocr_task(
        OcrPageTask(
            document_id="doc1",
            source_path="book.pdf",
            page_number=3,
            ocr_tier=OcrTier.SMALL,
            dpi=300,
            languages=("en",),
        )
    )

    assert result.succeeded
    assert result.page_number == 3
    assert result.text == "text for eng"
    assert result.extraction_method == "ocr:tesseract"


def test_page_worker_returns_error_for_unsupported_tier() -> None:
    result = run_page_ocr_task(
        OcrPageTask(
            document_id="doc1",
            source_path="book.pdf",
            page_number=1,
            ocr_tier=OcrTier.MEDIUM,
            dpi=300,
            languages=("en",),
        )
    )

    assert not result.succeeded
    assert "not implemented" in (result.error_message or "")
