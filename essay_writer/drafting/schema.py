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


@dataclass(frozen=True)
class StyleGuidanceGrade:
    """Self-graded checklist row. One per writing-style guidance bullet that the
    drafting or style-revision stage was asked to honor. Forces the model to
    explicitly own whether it followed each bullet, instead of letting style
    guidance read as advisory context."""

    bullet: str
    followed: bool
    where: str = ""  # quoted span or paragraph reference that demonstrates compliance
    why_not: str = ""  # explanation when followed is False


@dataclass(frozen=True)
class AntiAISkillLineAudit:
    """One line-level proof row for the anti-AI skill document."""

    line_number: int
    line_text_sha256: str
    requirement: str
    status: str
    evidence: str
    action_taken: str
    draft_evidence: list[dict[str, str]] = field(default_factory=list)
    whole_essay_evidence: dict[str, object] = field(default_factory=dict)
    line_application: str = ""


@dataclass(frozen=True)
class AntiAIUnmetRequirement:
    """A skill-line requirement the agent could not satisfy."""

    line_number: int
    section: str
    status: str
    reason: str
    risk: str


@dataclass(frozen=True)
class AntiAIFinalDecision:
    hard_rules_pass: bool
    soft_rules_pass: bool
    safe_to_claim_detector_reduction: bool
    reason: str


@dataclass(frozen=True)
class AntiAISelfCheck:
    """Anti-AI self-audit produced by the drafting and style-revision stages.

    The act of producing this object is the audit. Every field is verifiable
    against the draft `content` so the validator can spot self-grade mismatches.
    See the anti-AI skill 7-step self-check section."""

    skill_file: str = ""
    skill_sha256: str = ""
    skill_line_count: int = 0
    draft_sha256: str = ""
    line_audit: list[AntiAISkillLineAudit] = field(default_factory=list)
    paragraph_count: int = 0
    paragraph_first_sentences: list[str] = field(default_factory=list)
    first_sentence_chain_summarizes_essay: bool = True
    paragraphs_under_50_words: int = 0
    paragraphs_opening_with_topic_sentence: int = 0
    filler_phrases_used: list[str] = field(default_factory=list)
    significance_inflation_phrases: list[str] = field(default_factory=list)
    vague_attributions_used: list[str] = field(default_factory=list)
    concrete_source_handles: list[str] = field(default_factory=list)
    style_guidance_grades: list[StyleGuidanceGrade] = field(default_factory=list)
    self_check_notes: list[str] = field(default_factory=list)
    unmet_requirements: list[AntiAIUnmetRequirement] = field(default_factory=list)
    final_decision: AntiAIFinalDecision | None = None


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
    anti_ai_self_check: AntiAISelfCheck | None = None
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
