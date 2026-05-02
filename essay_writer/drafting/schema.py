from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SectionSourceMap:
    section_id: str
    heading: str
    note_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


DraftOrigin = Literal[
    "generated",
    "style_revision",
    "system_revision",
    "user_edit",
    "manual_llm_revision",
]

DraftActor = Literal["system", "user"]
DraftLens = Literal["evidence", "citations", "assignment_fit", "length", "tone", "anti_ai"]


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
    origin: DraftOrigin = "generated"
    created_by: DraftActor = "system"
    parent_draft_id: str | None = None
    parent_export_id: str | None = None
    manual_request_id: str | None = None
    user_instruction: str | None = None
    selected_lenses: list[DraftLens] = field(default_factory=list)
    prompt_version: str = "drafting-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")
