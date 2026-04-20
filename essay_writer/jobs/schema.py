from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


EssayJobStatus = Literal[
    "created",
    "task_spec_ready",
    "sources_ready",
    "topic_selection_ready",
    "research_planning_ready",
    "drafting_ready",
    "validation_ready",
    "validation_complete",
    "blocked",
    "error",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EssayJobErrorState:
    stage: str
    message: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class EssayJob:
    id: str
    status: EssayJobStatus = "created"
    current_stage: str = "created"
    task_spec_id: str | None = None
    source_ids: list[str] = field(default_factory=list)
    topic_round_ids: list[str] = field(default_factory=list)
    selected_topic_id: str | None = None
    selected_topic_round_id: str | None = None
    research_plan_id: str | None = None
    evidence_map_id: str | None = None
    outline_id: str | None = None
    draft_id: str | None = None
    validation_report_id: str | None = None
    final_export_id: str | None = None
    cost_so_far: float = 0.0
    error_state: EssayJobErrorState | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.cost_so_far < 0:
            raise ValueError("cost_so_far must be >= 0")
