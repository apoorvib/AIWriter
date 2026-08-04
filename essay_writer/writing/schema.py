from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _required(name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must be non-empty")


class WriteMode(str, Enum):
    IMMEDIATE = "immediate"
    DETAILED = "detailed"


class ResearchPolicy(str, Enum):
    AUTO = "auto"
    REQUIRED = "required"
    OFF = "off"


@dataclass(frozen=True)
class SkillSelection:
    skill_id: str
    version: str
    sha256: str
    reason: str = ""

    def __post_init__(self) -> None:
        _required("skill_id", self.skill_id)
        _required("version", self.version)
        _required("sha256", self.sha256)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillSelection":
        return cls(**data)


@dataclass(frozen=True)
class DeliverableSpec:
    deliverable_id: str
    format: str
    objective: str
    audience: str | None = None
    constraints: list[str] = field(default_factory=list)
    selected_skill_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _required("deliverable_id", self.deliverable_id)
        _required("format", self.format)
        _required("objective", self.objective)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeliverableSpec":
        return cls(**data)


@dataclass(frozen=True)
class WritingRun:
    writing_run_id: str
    raw_request: str
    status: str = "active"
    mode_hint: WriteMode | None = None
    research_policy: ResearchPolicy = ResearchPolicy.AUTO
    include_skill_ids: list[str] = field(default_factory=list)
    exclude_skill_ids: list[str] = field(default_factory=list)
    context_ids: list[str] = field(default_factory=list)
    brief_id: str | None = None
    research_id: str | None = None
    output_id: str | None = None
    blocked_on: list[str] = field(default_factory=list)
    revision_rounds: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _required("writing_run_id", self.writing_run_id)
        _required("raw_request", self.raw_request)
        if self.status not in {"active", "needs_input", "blocked", "complete", "error"}:
            raise ValueError(f"unsupported writing run status: {self.status}")
        if any(rounds < 0 or rounds > 2 for rounds in self.revision_rounds.values()):
            raise ValueError("revision rounds must be between 0 and 2")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingRun":
        payload = dict(data)
        mode = payload.get("mode_hint")
        payload["mode_hint"] = WriteMode(mode) if mode is not None else None
        payload["research_policy"] = ResearchPolicy(
            payload.get("research_policy", ResearchPolicy.AUTO.value)
        )
        payload["revision_rounds"] = {
            str(key): int(value)
            for key, value in dict(payload.get("revision_rounds", {})).items()
        }
        return cls(**payload)


@dataclass(frozen=True)
class WritingBrief:
    brief_id: str
    writing_run_id: str
    version: int
    mode: WriteMode
    purpose: str
    audience: str
    deliverables: list[DeliverableSpec]
    selected_skills: list[SkillSelection]
    assumptions: list[str] = field(default_factory=list)
    blocking_questions: list[str] = field(default_factory=list)
    research_needed: bool = False
    research_reasons: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _required("brief_id", self.brief_id)
        _required("writing_run_id", self.writing_run_id)
        _required("purpose", self.purpose)
        _required("audience", self.audience)
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.deliverables:
            raise ValueError("at least one deliverable is required")
        if len(self.deliverables) > 5:
            raise ValueError("a writing brief supports at most 5 deliverables")
        ids = [item.deliverable_id for item in self.deliverables]
        if len(ids) != len(set(ids)):
            raise ValueError("deliverable IDs must be unique")
        if len(self.blocking_questions) > 3:
            raise ValueError("at most 3 blocking questions are allowed")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingBrief":
        payload = dict(data)
        payload["mode"] = WriteMode(payload["mode"])
        payload["deliverables"] = [
            DeliverableSpec.from_dict(item) for item in payload.get("deliverables", [])
        ]
        payload["selected_skills"] = [
            SkillSelection.from_dict(item) for item in payload.get("selected_skills", [])
        ]
        return cls(**payload)


@dataclass(frozen=True)
class WritingContextItem:
    context_id: str
    writing_run_id: str
    label: str
    kind: str
    content_path: str
    content_sha256: str
    char_count: int
    source_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _required("context_id", self.context_id)
        _required("writing_run_id", self.writing_run_id)
        if self.char_count < 0:
            raise ValueError("char_count must be >= 0")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingContextItem":
        return cls(**data)


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    title: str
    url: str
    publisher: str | None = None
    published_at: str | None = None
    accessed_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchSource":
        return cls(**data)


@dataclass(frozen=True)
class ResearchFact:
    fact_id: str
    claim: str
    source_ids: list[str]
    confidence: str = "medium"
    short_quote: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchFact":
        return cls(**data)


@dataclass(frozen=True)
class WritingResearch:
    research_id: str
    writing_run_id: str
    version: int
    sources: list[ResearchSource]
    facts: list[ResearchFact]
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingResearch":
        payload = dict(data)
        payload["sources"] = [ResearchSource.from_dict(item) for item in payload["sources"]]
        payload["facts"] = [ResearchFact.from_dict(item) for item in payload["facts"]]
        return cls(**payload)


@dataclass(frozen=True)
class WritingPlan:
    plan_id: str
    writing_run_id: str
    deliverable_id: str
    version: int
    sections: list[str]
    key_points: list[str] = field(default_factory=list)
    research_fact_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingPlan":
        return cls(**data)


@dataclass(frozen=True)
class WritingDraft:
    draft_id: str
    writing_run_id: str
    deliverable_id: str
    version: int
    content: str
    selected_skills: list[SkillSelection]
    assumptions: list[str] = field(default_factory=list)
    research_fact_ids: list[str] = field(default_factory=list)
    self_check: list[str] = field(default_factory=list)
    origin: str = "draft"
    content_sha256: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _required("draft_id", self.draft_id)
        _required("writing_run_id", self.writing_run_id)
        _required("deliverable_id", self.deliverable_id)
        _required("content", self.content)
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", text_sha256(self.content))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingDraft":
        payload = dict(data)
        payload["selected_skills"] = [
            SkillSelection.from_dict(item) for item in payload.get("selected_skills", [])
        ]
        return cls(**payload)


@dataclass(frozen=True)
class ReviewIssue:
    issue_id: str
    severity: str
    location: str
    skill_id: str
    evidence: str
    correction: str
    category: str = "style"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewIssue":
        return cls(**data)


@dataclass(frozen=True)
class WritingReview:
    review_id: str
    writing_run_id: str
    deliverable_id: str
    version: int
    draft_id: str
    draft_sha256: str
    selected_skills: list[SkillSelection]
    passed: bool
    issues: list[ReviewIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingReview":
        payload = dict(data)
        payload["selected_skills"] = [
            SkillSelection.from_dict(item) for item in payload.get("selected_skills", [])
        ]
        payload["issues"] = [ReviewIssue.from_dict(item) for item in payload.get("issues", [])]
        return cls(**payload)


@dataclass(frozen=True)
class WritingOutput:
    output_id: str
    writing_run_id: str
    deliverables: list[WritingDraft]
    selected_skills: list[SkillSelection]
    assumptions: list[str] = field(default_factory=list)
    researched_sources: list[ResearchSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingOutput":
        payload = dict(data)
        payload["deliverables"] = [
            WritingDraft.from_dict(item) for item in payload.get("deliverables", [])
        ]
        payload["selected_skills"] = [
            SkillSelection.from_dict(item) for item in payload.get("selected_skills", [])
        ]
        payload["researched_sources"] = [
            ResearchSource.from_dict(item) for item in payload.get("researched_sources", [])
        ]
        return cls(**payload)
