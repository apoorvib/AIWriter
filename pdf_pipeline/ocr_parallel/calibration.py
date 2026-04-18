from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from time import perf_counter
from typing import Callable

from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.page_worker import run_page_ocr_task
from pdf_pipeline.ocr_parallel.schema import (
    CalibrationCandidateResult,
    CalibrationProfile,
    OcrPageResult,
    OcrPageTask,
    ParallelOcrConfig,
    SystemResources,
)

logger = logging.getLogger(__name__)

PageRunner = Callable[[OcrPageTask], OcrPageResult]


def calibrate_tesseract_workers(
    *,
    document_id: str,
    source_path: str,
    requested_pages: list[int],
    config: ParallelOcrConfig,
    resources: SystemResources,
    page_runner: PageRunner = run_page_ocr_task,
) -> CalibrationProfile:
    if config.ocr_tier != OcrTier.SMALL:
        raise ValueError("calibration currently supports only small/Tesseract OCR")
    sample_pages = select_sample_pages(requested_pages)
    candidates = candidate_worker_counts(resources, len(sample_pages))
    results = [
        _benchmark_candidate(
            workers=workers,
            sample_pages=sample_pages,
            document_id=document_id,
            source_path=source_path,
            config=config,
            page_runner=page_runner,
        )
        for workers in candidates
    ]
    selected_workers = _select_best_workers(results)
    marked_results = [
        CalibrationCandidateResult(
            workers=result.workers,
            sample_pages=result.sample_pages,
            elapsed_seconds=result.elapsed_seconds,
            successful_pages=result.successful_pages,
            failed_pages=result.failed_pages,
            pages_per_minute=result.pages_per_minute,
            selected=result.workers == selected_workers,
            error_message=result.error_message,
        )
        for result in results
    ]
    logger.info("OCR calibration selected %d workers", selected_workers)
    return CalibrationProfile(
        document_id=document_id,
        ocr_tier=config.ocr_tier,
        dpi=config.dpi,
        languages=config.languages,
        selected_workers=selected_workers,
        candidates=marked_results,
    )


def select_sample_pages(requested_pages: list[int]) -> list[int]:
    if len(requested_pages) <= 5:
        return list(requested_pages)
    indexes = {
        0,
        1,
        len(requested_pages) // 2,
        (len(requested_pages) * 3) // 4,
        len(requested_pages) - 1,
    }
    return [requested_pages[index] for index in sorted(indexes)]


def candidate_worker_counts(resources: SystemResources, sample_count: int) -> list[int]:
    base = [1, 2, 4, 6, 8, 12, 16]
    max_candidate = min(max(1, resources.physical_cores), max(1, sample_count), 16)
    candidates = [candidate for candidate in base if candidate <= max_candidate]
    if not candidates:
        return [1]
    return candidates


def _benchmark_candidate(
    *,
    workers: int,
    sample_pages: list[int],
    document_id: str,
    source_path: str,
    config: ParallelOcrConfig,
    page_runner: PageRunner,
) -> CalibrationCandidateResult:
    start = perf_counter()
    try:
        if workers == 1:
            results = [
                page_runner(_make_task(document_id, source_path, page, config))
                for page in sample_pages
            ]
        else:
            tasks = [_make_task(document_id, source_path, page, config) for page in sample_pages]
            results = []
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(page_runner, task) for task in tasks]
                for future in as_completed(futures):
                    results.append(future.result())
        elapsed = max(perf_counter() - start, 0.001)
        success = sum(1 for result in results if result.succeeded)
        failed = len(results) - success
        return CalibrationCandidateResult(
            workers=workers,
            sample_pages=sample_pages,
            elapsed_seconds=elapsed,
            successful_pages=success,
            failed_pages=failed,
            pages_per_minute=(success / elapsed) * 60.0,
        )
    except Exception as exc:  # pragma: no cover - process/runtime specific
        elapsed = max(perf_counter() - start, 0.001)
        return CalibrationCandidateResult(
            workers=workers,
            sample_pages=sample_pages,
            elapsed_seconds=elapsed,
            successful_pages=0,
            failed_pages=len(sample_pages),
            pages_per_minute=0.0,
            error_message=str(exc),
        )


def _select_best_workers(results: list[CalibrationCandidateResult]) -> int:
    viable = [result for result in results if result.failed_pages == 0 and result.successful_pages > 0]
    if not viable:
        return 1
    best = max(viable, key=lambda result: result.pages_per_minute)
    return best.workers


def _make_task(
    document_id: str,
    source_path: str,
    page_number: int,
    config: ParallelOcrConfig,
) -> OcrPageTask:
    return OcrPageTask(
        document_id=document_id,
        source_path=source_path,
        page_number=page_number,
        ocr_tier=config.ocr_tier,
        dpi=config.dpi,
        languages=config.languages,
        use_gpu=config.use_gpu,
        attempt=1,
        timeout_seconds=config.timeout_seconds,
    )
