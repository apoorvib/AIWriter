from __future__ import annotations

from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.calibration import (
    calibrate_tesseract_workers,
    candidate_worker_counts,
    select_sample_pages,
)
from pdf_pipeline.ocr_parallel.schema import (
    OcrPageResult,
    OcrPageTask,
    ParallelOcrConfig,
    SystemResources,
)


def test_select_sample_pages_keeps_small_ranges() -> None:
    assert select_sample_pages([1, 2, 3]) == [1, 2, 3]


def test_select_sample_pages_spreads_large_ranges() -> None:
    assert select_sample_pages(list(range(1, 21))) == [1, 2, 11, 16, 20]


def test_candidate_worker_counts_are_bounded_by_sample_count() -> None:
    resources = SystemResources(logical_cores=16, physical_cores=8)

    assert candidate_worker_counts(resources, sample_count=3) == [1, 2]


def test_calibration_selects_best_successful_candidate() -> None:
    resources = SystemResources(logical_cores=1, physical_cores=1)

    def page_runner(task: OcrPageTask) -> OcrPageResult:
        return OcrPageResult(
            document_id=task.document_id,
            source_path=task.source_path,
            page_number=task.page_number,
            text="ok",
            char_count=2,
            extraction_method="ocr:tesseract",
            rasterization_ms=1.0,
            ocr_ms=1.0,
            normalization_ms=1.0,
            worker_pid=1,
            attempt=1,
        )

    profile = calibrate_tesseract_workers(
        document_id="doc1",
        source_path="book.pdf",
        requested_pages=[1, 2, 3],
        config=ParallelOcrConfig(ocr_tier=OcrTier.SMALL),
        resources=resources,
        page_runner=page_runner,
    )

    assert profile.selected_workers == 1
    assert profile.candidates[0].selected is True
