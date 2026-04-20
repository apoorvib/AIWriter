from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from essay_writer.sources.access_schema import SourceLocator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TopicSourceLead:
    source_id: str
    chunk_ids: list[str] = field(default_factory=list)
    suggested_source_search_queries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateTopic:
    id: str
    title: str
    research_question: str
    tentative_thesis_direction: str
    rationale: str
    parent_topic_id: str | None = None
    novelty_note: str | None = None
    source_leads: list[TopicSourceLead] = field(default_factory=list)
    source_requests: list[SourceLocator] = field(default_factory=list)
    fit_score: float = 0.0
    evidence_score: float = 0.0
    originality_score: float = 0.0
    risk_flags: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name, score in [
            ("fit_score", self.fit_score),
            ("evidence_score", self.evidence_score),
            ("originality_score", self.originality_score),
        ]:
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")


@dataclass(frozen=True)
class TopicIdeationResult:
    task_spec_id: str
    candidates: list[CandidateTopic]
    blocking_questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    prompt_version: str = "topic-ideation-v1"


@dataclass(frozen=True)
class TopicIdeationRound:
    id: str
    job_id: str
    task_spec_id: str
    round_number: int
    user_instruction: str | None
    previous_topic_ids: list[str]
    candidates: list[CandidateTopic]
    prompt_version: str = "topic-ideation-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.round_number < 1:
            raise ValueError("round_number must be >= 1")


@dataclass(frozen=True)
class SelectedTopic:
    job_id: str
    round_id: str
    topic_id: str
    title: str
    research_question: str
    tentative_thesis_direction: str
    source_leads: list[TopicSourceLead] = field(default_factory=list)
    source_requests: list[SourceLocator] = field(default_factory=list)
    selected_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class RejectedTopic:
    job_id: str
    round_id: str
    topic_id: str
    title: str
    reason: str
    rejected_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class TopicEvidenceChunk:
    source_id: str
    chunk_id: str
    page_start: int
    page_end: int
    text: str
    score: float | None = None
    retrieval_method: str = "fts"


@dataclass(frozen=True)
class RetrievedTopicEvidence:
    topic_id: str
    chunks: list[TopicEvidenceChunk]
    warnings: list[str] = field(default_factory=list)
