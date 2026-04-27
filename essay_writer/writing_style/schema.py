from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class HumanWritingSample:
    id: str
    title: str
    source_filename: str
    source_type: str
    original_path: str
    artifact_dir: str
    extracted_text_path: str
    cleaned_text_path: str
    cleaned_text_hash: str
    page_count: int
    extraction_method: str
    char_count: int
    word_count: int
    warnings: list[str] = field(default_factory=list)
    normalizer_version: str = "human-sample-normalizer-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        for name, value in [
            ("page_count", self.page_count),
            ("char_count", self.char_count),
            ("word_count", self.word_count),
        ]:
            if value < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class StyleAnchorExcerpt:
    sample_id: str
    excerpt_id: str
    text: str
    role: str
    reason: str


@dataclass(frozen=True)
class WritingStyleContent:
    id: str
    version: int
    sample_ids: list[str]
    sample_fingerprint: str
    use_for: str = "tone_and_style_only"
    guidance: list[str] = field(default_factory=list)
    preferred_moves: list[str] = field(default_factory=list)
    avoid_moves: list[str] = field(default_factory=list)
    lexical_habits: list[str] = field(default_factory=list)
    structural_habits: list[str] = field(default_factory=list)
    anchor_excerpts: list[StyleAnchorExcerpt] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generator_model: str | None = None
    generator_version: str = "writing-style-content-v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be >= 1")


@dataclass(frozen=True)
class PromptSampleText:
    sample_id: str
    title: str
    cleaned_text: str
    cleaned_text_hash: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WritingStylePayload:
    style_content: WritingStyleContent
    samples: list[PromptSampleText] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedWritingSampleText:
    text: str
    char_count: int
    word_count: int
    warnings: list[str] = field(default_factory=list)

