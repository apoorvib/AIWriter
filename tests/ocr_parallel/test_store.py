from __future__ import annotations

from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.schema import OcrPageResult, WorkerPlan
from pdf_pipeline.ocr_parallel.store import OcrArtifactStore
from tests.ocr_parallel._tmp import LocalTempDir


def test_store_round_trips_page_result() -> None:
    with LocalTempDir() as tmp_path:
        store = OcrArtifactStore(tmp_path)
        worker_plan = WorkerPlan(
            ocr_tier=OcrTier.SMALL,
            physical_cores=4,
            logical_cores=8,
            total_ram_gb=16.0,
            available_ram_gb=12.0,
            selected_workers=2,
            max_workers=4,
            omp_thread_limit=1,
            source="manual_override",
            reason="test",
        )
        store.init_document("doc1", {"source_path": "book.pdf"}, worker_plan)
        result = OcrPageResult(
            document_id="doc1",
            source_path="book.pdf",
            page_number=1,
            text="hello",
            char_count=5,
            extraction_method="ocr:tesseract",
            rasterization_ms=1.0,
            ocr_ms=2.0,
            normalization_ms=0.5,
            worker_pid=123,
            attempt=1,
        )

        store.save_page_result(result)
        loaded = store.load_page_result("doc1", 1)

        assert loaded == result


def test_store_writes_merged_result() -> None:
    with LocalTempDir() as tmp_path:
        store = OcrArtifactStore(tmp_path)
        merged = DocumentExtractionResult(
            source_path="book.pdf",
            page_count=1,
            pages=[PageText(page_number=1, text="hello", char_count=5, extraction_method="ocr:tesseract")],
        )

        path = store.save_merged_result("doc1", merged)

        assert path.exists()
