from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VocabHit:
    word: str
    count: int


@dataclass(frozen=True)
class SentenceRun:
    sentence_count: int
    avg_word_count: float


@dataclass(frozen=True)
class ParagraphLengthProfile:
    paragraph_count: int
    shortest_word_count: int
    longest_word_count: int
    longest_to_shortest_ratio: float


@dataclass(frozen=True)
class DeterministicCheckResult:
    word_count: int
    em_dash_count: int
    tier1_vocab_hits: list[VocabHit]
    bad_conclusion_opener: bool
    consecutive_similar_sentence_runs: list[SentenceRun]
    participial_phrase_count: int
    participial_phrase_rate: float
    contrastive_negation_count: int
    signposting_hits: list[str]
    en_dash_count: int = 0
    decorative_hyphen_pause_count: int = 0
    colon_explanation_pattern_count: int = 0
    triplet_contrastive_combo_count: int = 0
    clustered_triplet_count: int = 0
    paragraph_length_profile: ParagraphLengthProfile | None = None
    paragraph_length_variance_warning: bool = False
    mechanical_burstiness_count: int = 0
    concrete_engagement_present: bool = False

    @property
    def has_issues(self) -> bool:
        return (
            self.em_dash_count > 0
            or self.en_dash_count > 0
            or self.decorative_hyphen_pause_count > 0
            or self.colon_explanation_pattern_count > 0
            or len(self.tier1_vocab_hits) > 0
            or self.bad_conclusion_opener
            or len(self.consecutive_similar_sentence_runs) > 0
            or self.participial_phrase_rate > 1.0
            or self.contrastive_negation_count > 0
            or len(self.signposting_hits) > 0
            or self.triplet_contrastive_combo_count > 0
            or self.clustered_triplet_count > 0
            or self.paragraph_length_variance_warning
            or self.mechanical_burstiness_count > 0
        )



@dataclass(frozen=True)
class UnsupportedClaim:
    claim: str
    paragraph: int


@dataclass(frozen=True)
class CitationIssue:
    description: str
    severity: str


@dataclass(frozen=True)
class CitationMetadataWarning:
    source_id: str
    description: str
    severity: str = "medium"


@dataclass(frozen=True)
class RubricScore:
    criterion: str
    score: float
    note: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")


@dataclass(frozen=True)
class AssignmentFit:
    passes: bool
    explanation: str


@dataclass(frozen=True)
class LengthCheck:
    actual_words: int
    target_words: int | None
    passes: bool


@dataclass(frozen=True)
class StyleIssue:
    issue_type: str
    description: str


@dataclass(frozen=True)
class ValidationDiagnostic:
    location: str
    issue_type: str
    evidence: str
    severity: str
    action: str


@dataclass(frozen=True)
class LLMJudgmentResult:
    unsupported_claims: list[UnsupportedClaim]
    citation_issues: list[CitationIssue]
    rubric_scores: list[RubricScore]
    assignment_fit: AssignmentFit
    length_check: LengthCheck
    style_issues: list[StyleIssue]
    overall_quality: float
    diagnostics: list[ValidationDiagnostic] = field(default_factory=list)
    revision_suggestions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.overall_quality <= 1.0:
            raise ValueError("overall_quality must be between 0.0 and 1.0")


@dataclass(frozen=True)
class ValidationReport:
    draft_id: str
    task_spec_id: str
    deterministic: DeterministicCheckResult
    llm_judgment: LLMJudgmentResult
    metadata_citation_warnings: list[CitationMetadataWarning] = field(default_factory=list)
    prompt_version: str = "validation-v1"
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def passes(self) -> bool:
        return (
            self.llm_judgment.assignment_fit.passes
            and self.llm_judgment.length_check.passes
            and not self.llm_judgment.unsupported_claims
            and not self.deterministic.em_dash_count
            and not self.deterministic.en_dash_count
            and not self.deterministic.decorative_hyphen_pause_count
            and not self.deterministic.colon_explanation_pattern_count
        )
