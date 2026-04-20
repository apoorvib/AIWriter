from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


EvidenceType = Literal[
    "background",
    "argument",
    "example",
    "counterargument",
    "statistic",
    "definition",
    "other",
]

EvidenceGroupPurpose = Literal[
    "thesis_support",
    "background",
    "counterargument",
    "example",
    "limitation",
    "other",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchNote:
    id: str
    source_id: str
    chunk_id: str
    page_start: int
    page_end: int
    claim: str
    quote: str | None
    paraphrase: str
    relevance: str
    supports_topic: bool
    evidence_type: EvidenceType
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.page_start < 1 or self.page_end < self.page_start:
            raise ValueError("invalid page range")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class EvidenceGroup:
    id: str
    label: str
    purpose: EvidenceGroupPurpose
    note_ids: list[str]
    synthesis: str


@dataclass(frozen=True)
class EvidenceMap:
    id: str
    job_id: str
    selected_topic_id: str
    research_question: str
    thesis_direction: str
    notes: list[ResearchNote]
    evidence_groups: list[EvidenceGroup] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    prompt_version: str = "final-topic-research-v1"


@dataclass(frozen=True)
class ResearchReport:
    job_id: str
    selected_topic_id: str
    evidence_map_id: str
    note_count: int
    source_count: int
    gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class FinalTopicResearchResult:
    evidence_map: EvidenceMap
    report: ResearchReport
