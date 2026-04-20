from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from essay_writer.sources.access_schema import SourceLocator


ResearchPriority = Literal["high", "medium", "low"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceReadingPriority:
    source_id: str
    priority: ResearchPriority
    rationale: str
    chunk_ids: list[str] = field(default_factory=list)
    suggested_source_search_queries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchPlan:
    id: str
    job_id: str
    selected_topic_id: str
    version: int
    research_question: str
    source_requirements: list[str]
    uploaded_source_priorities: list[SourceReadingPriority]
    expected_evidence_categories: list[str]
    source_requests: list[SourceLocator] = field(default_factory=list)
    external_search_allowed: bool = False
    external_search_queries: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prompt_version: str = "research-planning-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.external_search_queries and not self.external_search_allowed:
            raise ValueError("external_search_queries require external_search_allowed=True")
