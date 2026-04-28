from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ToneAlignmentConflict:
    issue_type: str
    anti_ai_signal: str
    tone_signal: str
    resolution: str = "prefer_tone"
    rationale: str = ""


@dataclass(frozen=True)
class ToneAlignmentReport:
    draft_id: str
    writing_style_content_id: str
    overall_alignment: float
    requires_revision: bool
    matched_habits: list[str] = field(default_factory=list)
    mismatched_habits: list[str] = field(default_factory=list)
    preserve_points: list[str] = field(default_factory=list)
    revision_targets: list[str] = field(default_factory=list)
    anti_ai_conflicts: list[ToneAlignmentConflict] = field(default_factory=list)
    prompt_version: str = "tone-alignment-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not 0.0 <= self.overall_alignment <= 1.0:
            raise ValueError("overall_alignment must be between 0.0 and 1.0")

