from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class OutlineSection:
    id: str
    heading: str
    purpose: str
    key_points: list[str] = field(default_factory=list)
    note_ids: list[str] = field(default_factory=list)
    target_words: int | None = None


@dataclass(frozen=True)
class ThesisOutline:
    id: str
    job_id: str
    selected_topic_id: str
    research_plan_id: str
    evidence_map_id: str
    version: int
    working_thesis: str
    sections: list[OutlineSection]
    prompt_version: str = "thesis-outline-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.sections:
            raise ValueError("outline must contain at least one section")
