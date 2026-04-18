"""Parallel OCR scheduling utilities."""

from pdf_pipeline.ocr_parallel.scheduler import run_parallel_ocr
from pdf_pipeline.ocr_parallel.schema import (
    OcrPageResult,
    OcrPageTask,
    OcrRunSummary,
    ParallelOcrConfig,
    SystemResources,
    WorkerPlan,
)

__all__ = [
    "OcrPageResult",
    "OcrPageTask",
    "OcrRunSummary",
    "ParallelOcrConfig",
    "SystemResources",
    "WorkerPlan",
    "run_parallel_ocr",
]
