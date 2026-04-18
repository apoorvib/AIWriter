from __future__ import annotations

import pytest

from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.planner import plan_workers
from pdf_pipeline.ocr_parallel.schema import ParallelOcrConfig, SystemResources


def _resources() -> SystemResources:
    return SystemResources(
        logical_cores=16,
        physical_cores=8,
        total_ram_gb=32.0,
        available_ram_gb=16.0,
    )


def test_manual_worker_count_wins() -> None:
    plan = plan_workers(ParallelOcrConfig(workers=6), _resources())

    assert plan.selected_workers == 6
    assert plan.source == "manual_override"


def test_shared_machine_uses_conservative_default() -> None:
    plan = plan_workers(ParallelOcrConfig(shared_machine=True), _resources())

    assert plan.selected_workers == 4
    assert plan.source == "static_heuristic"


def test_dedicated_machine_uses_physical_cores() -> None:
    plan = plan_workers(ParallelOcrConfig(shared_machine=False), _resources())

    assert plan.selected_workers == 8


def test_ram_bound_limits_workers() -> None:
    resources = SystemResources(
        logical_cores=32,
        physical_cores=16,
        total_ram_gb=64.0,
        available_ram_gb=3.1,
    )

    plan = plan_workers(ParallelOcrConfig(shared_machine=False), resources)

    assert plan.selected_workers == 2


def test_non_small_tier_is_not_marked_parallel() -> None:
    plan = plan_workers(ParallelOcrConfig(ocr_tier=OcrTier.MEDIUM), _resources())

    assert plan.selected_workers == 1
    assert plan.reason == "medium parallel workers are not implemented yet"


def test_invalid_worker_count_raises() -> None:
    with pytest.raises(ValueError):
        plan_workers(ParallelOcrConfig(workers=0), _resources())
