from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


ChecklistCategory = Literal[
    "topic",
    "source",
    "citation",
    "structure",
    "formatting",
    "rubric",
    "submission",
    "style",
    "material",
    "content",
    "other",
]

AdversarialCategory = Literal[
    "prompt_injection",
    "system_prompt_extraction",
    "model_behavior_override",
    "sabotage",
    "irrelevant_ai_directive",
    "other",
]

Severity = Literal["low", "medium", "high"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    text: str
    category: ChecklistCategory
    required: bool
    source_span: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class AdversarialFlag:
    id: str
    text: str
    category: AdversarialCategory
    severity: Severity
    source_span: str
    recommended_action: str


@dataclass(frozen=True)
class TaskSpecification:
    id: str
    version: int
    raw_text: str
    source_document_ids: list[str] = field(default_factory=list)
    assignment_title: str | None = None
    course_context: str | None = None
    essay_type: str | None = None
    academic_level: str | None = None
    target_length: int | None = None
    length_unit: str | None = None
    citation_style: str | None = None
    required_sources: list[str] = field(default_factory=list)
    allowed_sources: list[str] = field(default_factory=list)
    forbidden_sources: list[str] = field(default_factory=list)
    topic_scope: str | None = None
    prompt_options: list[str] = field(default_factory=list)
    selected_prompt: str | None = None
    required_materials: list[str] = field(default_factory=list)
    required_claims_or_questions: list[str] = field(default_factory=list)
    required_structure: list[str] = field(default_factory=list)
    formatting_requirements: list[str] = field(default_factory=list)
    rubric: list[str] = field(default_factory=list)
    grading_criteria: list[str] = field(default_factory=list)
    submission_requirements: list[str] = field(default_factory=list)
    professor_constraints: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    adversarial_flags: list[AdversarialFlag] = field(default_factory=list)
    ignored_ai_directives: list[str] = field(default_factory=list)
    extracted_checklist: list[ChecklistItem] = field(default_factory=list)
    blocking_questions: list[str] = field(default_factory=list)
    nonblocking_warnings: list[str] = field(default_factory=list)
    confidence_by_field: dict[str, float] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    parser_version: str = "task-spec-v1"

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")
        for field_name, confidence in self.confidence_by_field.items():
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"confidence_by_field[{field_name!r}] must be between 0.0 and 1.0")
