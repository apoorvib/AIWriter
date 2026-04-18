from __future__ import annotations

import os

from pdf_pipeline.ocr_parallel.schema import SystemResources


def detect_system_resources() -> SystemResources:
    logical = os.cpu_count() or 1
    physical = logical
    total_ram_gb: float | None = None
    available_ram_gb: float | None = None

    try:
        import psutil
    except ImportError:
        return SystemResources(
            logical_cores=logical,
            physical_cores=physical,
            total_ram_gb=total_ram_gb,
            available_ram_gb=available_ram_gb,
        )

    detected_physical = psutil.cpu_count(logical=False)
    if detected_physical:
        physical = detected_physical
    memory = psutil.virtual_memory()
    total_ram_gb = memory.total / (1024**3)
    available_ram_gb = memory.available / (1024**3)
    return SystemResources(
        logical_cores=logical,
        physical_cores=physical,
        total_ram_gb=total_ram_gb,
        available_ram_gb=available_ram_gb,
    )
