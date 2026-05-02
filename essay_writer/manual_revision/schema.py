from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from essay_writer.drafting.schema import DraftLens
from essay_writer.tone_alignment.schema import ToneAlignmentReport
from essay_writer.validation.schema import DeterministicCheckResult, ValidationReport


ManualRevisionMode = Literal["review_only", "revise"]
ManualRevisionStatus = Literal["completed", "failed"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ManualRevisionRequest:
    id: str
    job_id: str
    source_draft_id: str
    mode: ManualRevisionMode
    instruction: str | None
    selected_lenses: list[DraftLens] = field(default_factory=list)
    preserve_user_edits: bool = True
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class ManualRevisionRun:
    id: str
    request_id: str
    job_id: str
    source_draft_id: str
    mode: ManualRevisionMode
    instruction: str | None
    selected_lenses: list[DraftLens] = field(default_factory=list)
    change_summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pre_revision_validation: ValidationReport | None = None
    pre_revision_tone_alignment: ToneAlignmentReport | None = None
    pre_revision_anti_ai: DeterministicCheckResult | None = None
    result_draft_id: str | None = None
    post_revision_validation: ValidationReport | None = None
    post_revision_tone_alignment: ToneAlignmentReport | None = None
    post_revision_anti_ai: DeterministicCheckResult | None = None
    status: ManualRevisionStatus = "completed"
    created_at: str = field(default_factory=utc_now_iso)
