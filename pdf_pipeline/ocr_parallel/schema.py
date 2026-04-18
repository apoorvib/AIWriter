from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pdf_pipeline.ocr import OcrTier


WorkerPlanSource = Literal["manual_override", "cached_calibration", "static_heuristic", "default"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SystemResources:
    logical_cores: int
    physical_cores: int
    total_ram_gb: float | None = None
    available_ram_gb: float | None = None
    cpu_name: str | None = None


@dataclass(frozen=True)
class WorkerPlan:
    ocr_tier: OcrTier
    physical_cores: int
    logical_cores: int
    total_ram_gb: float | None
    available_ram_gb: float | None
    selected_workers: int
    max_workers: int
    omp_thread_limit: int
    source: WorkerPlanSource
    reason: str


@dataclass(frozen=True)
class ParallelOcrConfig:
    ocr_tier: OcrTier = OcrTier.SMALL
    languages: tuple[str, ...] = ("en",)
    dpi: int = 300
    use_gpu: bool = False
    start_page: int = 1
    max_pages: int | None = None
    workers: int | str = "auto"
    calibrate: bool = False
    max_attempts: int = 2
    timeout_seconds: int | None = None
    store_path: str | Path = "./ocr_store"
    document_id: str | None = None
    shared_machine: bool | None = None
    omp_thread_limit: int | None = None


@dataclass(frozen=True)
class OcrPageTask:
    document_id: str
    source_path: str
    page_number: int
    ocr_tier: OcrTier
    dpi: int
    languages: tuple[str, ...]
    use_gpu: bool = False
    attempt: int = 1
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class OcrPageResult:
    document_id: str
    source_path: str
    page_number: int
    text: str
    char_count: int
    extraction_method: str
    rasterization_ms: float
    ocr_ms: float
    normalization_ms: float
    worker_pid: int
    attempt: int
    created_at: str = field(default_factory=utc_now_iso)
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_message is None


@dataclass(frozen=True)
class OcrRunSummary:
    run_id: str
    document_id: str
    source_path: str
    page_count: int
    requested_pages: list[int]
    successful_pages: list[int]
    failed_pages: list[int]
    ocr_tier: OcrTier
    dpi: int
    languages: tuple[str, ...]
    selected_workers: int
    worker_plan_source: WorkerPlanSource
    started_at: str
    completed_at: str
    elapsed_seconds: float
    pages_per_minute: float
    failures: dict[int, str]
    store_path: str
