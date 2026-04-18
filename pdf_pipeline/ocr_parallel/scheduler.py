from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pdf_pipeline.extractors.ocr_common import get_pdf_page_count
from pdf_pipeline.models import DocumentExtractionResult
from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.merge import merge_page_results
from pdf_pipeline.ocr_parallel.page_worker import run_page_ocr_task
from pdf_pipeline.ocr_parallel.planner import plan_workers
from pdf_pipeline.ocr_parallel.schema import (
    OcrPageResult,
    OcrPageTask,
    OcrRunSummary,
    ParallelOcrConfig,
    utc_now_iso,
)
from pdf_pipeline.ocr_parallel.store import OcrArtifactStore
from pdf_pipeline.ocr_parallel.system import detect_system_resources

logger = logging.getLogger(__name__)


def run_parallel_ocr(pdf_path: str | Path, config: ParallelOcrConfig | None = None) -> tuple[OcrRunSummary, DocumentExtractionResult]:
    config = config or ParallelOcrConfig()
    path = Path(pdf_path)
    if config.ocr_tier != OcrTier.SMALL:
        raise ValueError(
            f"ocr-parallel currently supports only small/Tesseract OCR, got: {config.ocr_tier.value}"
        )
    if config.max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got: {config.max_attempts}")

    page_count = get_pdf_page_count(path)
    requested_pages = _requested_pages(page_count, config.start_page, config.max_pages)
    document_id = config.document_id or _document_id_for_path(path)
    resources = detect_system_resources()
    worker_plan = plan_workers(config, resources)
    selected_workers = min(worker_plan.selected_workers, max(1, len(requested_pages)))
    if config.calibrate:
        logger.warning("OCR calibration is not implemented yet; using %s worker plan", worker_plan.source)

    os.environ["OMP_THREAD_LIMIT"] = str(worker_plan.omp_thread_limit)

    store = OcrArtifactStore(config.store_path)
    store.init_document(
        document_id,
        config={**asdict(config), "source_path": str(path), "page_count": page_count},
        worker_plan=worker_plan,
    )

    started_at = utc_now_iso()
    start = perf_counter()
    run_id = str(uuid4())
    logger.info(
        "Starting parallel OCR: document_id=%s pages=%d workers=%d tier=%s dpi=%d",
        document_id,
        len(requested_pages),
        selected_workers,
        config.ocr_tier.value,
        config.dpi,
    )

    final_results: dict[int, OcrPageResult] = {}
    failures: dict[int, str] = {}
    completed = 0

    if selected_workers == 1:
        for page_number in requested_pages:
            task = _make_task(document_id, path, page_number, config, attempt=1)
            result = run_page_ocr_task(task)
            while not result.succeeded and task.attempt < config.max_attempts:
                logger.warning(
                    "Retrying OCR page %d after attempt %d failed: %s",
                    task.page_number,
                    task.attempt,
                    result.error_message,
                )
                task = _make_task(document_id, path, task.page_number, config, attempt=task.attempt + 1)
                result = run_page_ocr_task(task)
            completed = _record_completed_result(
                result, store, final_results, failures, completed, len(requested_pages), start
            )
    else:
        with ProcessPoolExecutor(max_workers=selected_workers) as pool:
            futures: dict[Future[OcrPageResult], OcrPageTask] = {}
            for page_number in requested_pages:
                task = _make_task(document_id, path, page_number, config, attempt=1)
                futures[pool.submit(run_page_ocr_task, task)] = task

            while futures:
                for future in as_completed(list(futures)):
                    task = futures.pop(future)
                    result = _future_result(future, task)
                    if not result.succeeded and task.attempt < config.max_attempts:
                        retry = _make_task(document_id, path, task.page_number, config, attempt=task.attempt + 1)
                        futures[pool.submit(run_page_ocr_task, retry)] = retry
                        logger.warning(
                            "Retrying OCR page %d after attempt %d failed: %s",
                            task.page_number,
                            task.attempt,
                            result.error_message,
                        )
                        continue

                    completed = _record_completed_result(
                        result, store, final_results, failures, completed, len(requested_pages), start
                    )

    elapsed_seconds = perf_counter() - start
    ordered_results = [final_results[page] for page in sorted(final_results)]
    merged = merge_page_results(str(path), page_count, ordered_results)
    store.save_merged_result(document_id, merged)

    successful_pages = [result.page_number for result in ordered_results if result.succeeded]
    failed_pages = [result.page_number for result in ordered_results if not result.succeeded]
    summary = OcrRunSummary(
        run_id=run_id,
        document_id=document_id,
        source_path=str(path),
        page_count=page_count,
        requested_pages=requested_pages,
        successful_pages=successful_pages,
        failed_pages=failed_pages,
        ocr_tier=config.ocr_tier,
        dpi=config.dpi,
        languages=config.languages,
        selected_workers=selected_workers,
        worker_plan_source=worker_plan.source,
        started_at=started_at,
        completed_at=utc_now_iso(),
        elapsed_seconds=elapsed_seconds,
        pages_per_minute=(len(ordered_results) / elapsed_seconds * 60.0) if elapsed_seconds else 0.0,
        failures=failures,
        store_path=str(store.root),
    )
    store.save_run_summary(summary)
    return summary, merged


def _requested_pages(page_count: int, start_page: int, max_pages: int | None) -> list[int]:
    if start_page < 1:
        raise ValueError(f"start_page must be >= 1, got: {start_page}")
    if max_pages is not None and max_pages < 1:
        raise ValueError(f"max_pages must be >= 1, got: {max_pages}")
    if start_page > page_count:
        return []
    end_page = page_count
    if max_pages is not None:
        end_page = min(page_count, start_page + max_pages - 1)
    return list(range(start_page, end_page + 1))


def _make_task(
    document_id: str,
    path: Path,
    page_number: int,
    config: ParallelOcrConfig,
    attempt: int,
) -> OcrPageTask:
    return OcrPageTask(
        document_id=document_id,
        source_path=str(path),
        page_number=page_number,
        ocr_tier=config.ocr_tier,
        dpi=config.dpi,
        languages=config.languages,
        use_gpu=config.use_gpu,
        attempt=attempt,
        timeout_seconds=config.timeout_seconds,
    )


def _future_result(future: Future[OcrPageResult], task: OcrPageTask) -> OcrPageResult:
    try:
        return future.result()
    except Exception as exc:  # pragma: no cover - worker process failure
        return OcrPageResult(
            document_id=task.document_id,
            source_path=task.source_path,
            page_number=task.page_number,
            text="",
            char_count=0,
            extraction_method=f"ocr:{task.ocr_tier.value}",
            rasterization_ms=0.0,
            ocr_ms=0.0,
            normalization_ms=0.0,
            worker_pid=0,
            attempt=task.attempt,
            error_message=str(exc),
        )


def _record_completed_result(
    result: OcrPageResult,
    store: OcrArtifactStore,
    final_results: dict[int, OcrPageResult],
    failures: dict[int, str],
    completed: int,
    total_pages: int,
    start: float,
) -> int:
    store.save_page_result(result)
    final_results[result.page_number] = result
    if result.succeeded:
        failures.pop(result.page_number, None)
    else:
        failures[result.page_number] = result.error_message or "unknown OCR failure"
    completed += 1
    if completed == 1 or completed % 10 == 0 or completed == total_pages:
        elapsed = max(perf_counter() - start, 0.001)
        logger.info(
            "OCR progress: %d/%d pages complete, failed=%d, rate=%.2f pages/min",
            completed,
            total_pages,
            len(failures),
            completed / elapsed * 60.0,
        )
    return completed


def _document_id_for_path(path: Path) -> str:
    stat = path.stat()
    fingerprint = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"{path.stem}-{digest}"
