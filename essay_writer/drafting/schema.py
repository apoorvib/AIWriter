from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SectionSourceMap:
    section_id: str
    heading: str
    note_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EssayDraft:
    id: str
    job_id: str
    version: int
    selected_topic_id: str
    content: str
    outline_id: str | None = None
    citation_style: str | None = None
    section_source_map: list[SectionSourceMap] = field(default_factory=list)
    bibliography_candidates: list[str] = field(default_factory=list)
    known_weak_spots: list[str] = field(default_factory=list)
    prompt_version: str = "drafting-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")
