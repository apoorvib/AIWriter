from __future__ import annotations

import os

from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.schema import ParallelOcrConfig, SystemResources, WorkerPlan


DEFAULT_MEMORY_PER_TESSERACT_WORKER_GB = 1.5


def plan_workers(config: ParallelOcrConfig, resources: SystemResources) -> WorkerPlan:
    if config.ocr_tier != OcrTier.SMALL:
        return WorkerPlan(
            ocr_tier=config.ocr_tier,
            physical_cores=resources.physical_cores,
            logical_cores=resources.logical_cores,
            total_ram_gb=resources.total_ram_gb,
            available_ram_gb=resources.available_ram_gb,
            selected_workers=1,
            max_workers=1,
            omp_thread_limit=_resolve_omp_thread_limit(config),
            source="default",
            reason=f"{config.ocr_tier.value} parallel workers are not implemented yet",
        )

    manual = _resolve_manual_workers(config.workers)
    if manual is None:
        manual = _resolve_env_int("OCR_MAX_WORKERS")
    if manual is not None:
        selected = _bounded_workers(manual, resources)
        return WorkerPlan(
            ocr_tier=config.ocr_tier,
            physical_cores=resources.physical_cores,
            logical_cores=resources.logical_cores,
            total_ram_gb=resources.total_ram_gb,
            available_ram_gb=resources.available_ram_gb,
            selected_workers=selected,
            max_workers=selected,
            omp_thread_limit=_resolve_omp_thread_limit(config),
            source="manual_override",
            reason="worker count provided by CLI or OCR_MAX_WORKERS",
        )

    shared = _resolve_shared_machine(config)
    if shared:
        base = min(max(1, resources.physical_cores // 2), 8)
        reason = "shared-machine heuristic"
    else:
        base = min(max(1, resources.physical_cores), 16)
        reason = "dedicated-machine heuristic"

    selected = _bounded_workers(base, resources)
    return WorkerPlan(
        ocr_tier=config.ocr_tier,
        physical_cores=resources.physical_cores,
        logical_cores=resources.logical_cores,
        total_ram_gb=resources.total_ram_gb,
        available_ram_gb=resources.available_ram_gb,
        selected_workers=selected,
        max_workers=base,
        omp_thread_limit=_resolve_omp_thread_limit(config),
        source="static_heuristic",
        reason=reason,
    )


def _resolve_manual_workers(workers: int | str) -> int | None:
    if isinstance(workers, int):
        return workers
    if workers == "auto":
        return None
    try:
        return int(workers)
    except ValueError as exc:
        raise ValueError(f"workers must be 'auto' or a positive integer, got: {workers!r}") from exc


def _resolve_env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer, got: {value!r}") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be >= 1, got: {parsed}")
    return parsed


def _resolve_bool_env(name: str) -> bool | None:
    value = os.environ.get(name)
    if value in (None, ""):
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value, got: {value!r}")


def _resolve_shared_machine(config: ParallelOcrConfig) -> bool:
    if config.shared_machine is not None:
        return config.shared_machine
    env_value = _resolve_bool_env("OCR_SHARED_MACHINE")
    if env_value is not None:
        return env_value
    return True


def _resolve_omp_thread_limit(config: ParallelOcrConfig) -> int:
    if config.omp_thread_limit is not None:
        if config.omp_thread_limit < 1:
            raise ValueError("omp_thread_limit must be >= 1")
        return config.omp_thread_limit
    env_value = _resolve_env_int("OCR_OMP_THREAD_LIMIT")
    return env_value or 1


def _bounded_workers(workers: int, resources: SystemResources) -> int:
    if workers < 1:
        raise ValueError(f"worker count must be >= 1, got: {workers}")
    selected = workers
    if resources.available_ram_gb is not None:
        ram_bound = int(resources.available_ram_gb // DEFAULT_MEMORY_PER_TESSERACT_WORKER_GB)
        selected = min(selected, max(1, ram_bound))
    return max(1, selected)
