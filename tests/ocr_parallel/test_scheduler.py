from __future__ import annotations

from pdf_pipeline.ocr_parallel.schema import (
    OcrPageResult,
    ParallelOcrConfig,
    SystemResources,
)
from pdf_pipeline.ocr_parallel.scheduler import run_parallel_ocr
from tests.ocr_parallel._tmp import LocalTempDir


def test_scheduler_reuses_successful_page_artifacts_with_resume(monkeypatch) -> None:
    import pdf_pipeline.ocr_parallel.scheduler as module

    monkeypatch.setattr(module, "get_pdf_page_count", lambda _path: 2)
    monkeypatch.setattr(
        module,
        "detect_system_resources",
        lambda: SystemResources(logical_cores=1, physical_cores=1, available_ram_gb=8.0),
    )

    calls: list[int] = []

    def fake_runner(task):
        calls.append(task.page_number)
        return OcrPageResult(
            document_id=task.document_id,
            source_path=task.source_path,
            page_number=task.page_number,
            text=f"page {task.page_number}",
            char_count=6,
            extraction_method="ocr:tesseract",
            rasterization_ms=1.0,
            ocr_ms=1.0,
            normalization_ms=1.0,
            worker_pid=1,
            attempt=task.attempt,
        )

    monkeypatch.setattr(module, "run_page_ocr_task", fake_runner)
    with LocalTempDir() as tmp_path:
        pdf_path = tmp_path / "book.pdf"
        pdf_path.write_bytes(b"%PDF-pretend")
        config = ParallelOcrConfig(
            workers=1,
            max_pages=2,
            store_path=tmp_path / "store",
            document_id="doc1",
        )

        first_summary, first = run_parallel_ocr(pdf_path, config=config)
        second_summary, second = run_parallel_ocr(
            pdf_path,
            config=ParallelOcrConfig(
                workers=1,
                max_pages=2,
                store_path=tmp_path / "store",
                document_id="doc1",
                resume=True,
            ),
        )

        assert calls == [1, 2]
        assert first_summary.successful_pages == [1, 2]
        assert second_summary.successful_pages == [1, 2]
        assert [page.text for page in first.pages] == ["page 1", "page 2"]
        assert [page.text for page in second.pages] == ["page 1", "page 2"]
