from __future__ import annotations

import json
from typing import Any

from llm.client import LLMClient
from essay_writer.research.schema import ResearchNote
from essay_writer.sources.schema import SourceCard
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.validation.checks import run_deterministic_checks
from essay_writer.validation.citations import (
    check_bibliography_against_source_cards,
    source_metadata_context,
)
from essay_writer.validation.prompts import VALIDATION_SCHEMA, VALIDATION_SYSTEM_PROMPT
from essay_writer.validation.schema import (
    AssignmentFit,
    CitationIssue,
    CitationMetadataWarning,
    DeterministicCheckResult,
    LengthCheck,
    LLMJudgmentResult,
    RubricScore,
    StyleIssue,
    UnsupportedClaim,
    ValidationReport,
)


class ValidationService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "validation-v1",
    ) -> None:
        self._llm = llm_client
        self._prompt_version = prompt_version

    def validate(
        self,
        draft_text: str,
        *,
        draft_id: str,
        task_spec: TaskSpecification,
        evidence_map: list[ResearchNote],
        bibliography_candidates: list[str] | None = None,
        source_cards: list[SourceCard] | None = None,
        model: str | None = None,
    ) -> ValidationReport:
        det = run_deterministic_checks(draft_text)
        bibliography_candidates = bibliography_candidates or []
        source_cards = source_cards or []
        metadata_warnings = check_bibliography_against_source_cards(
            bibliography_candidates,
            source_cards,
        )
        payload = self._llm.chat_json(
            system=VALIDATION_SYSTEM_PROMPT,
            user=_build_user_message(
                draft_text,
                task_spec=task_spec,
                evidence_map=evidence_map,
                det=det,
                bibliography_candidates=bibliography_candidates,
                source_cards=source_cards,
                metadata_warnings=metadata_warnings,
            ),
            json_schema=VALIDATION_SCHEMA,
            max_tokens=4000,
            model=model,
        )
        return ValidationReport(
            draft_id=draft_id,
            task_spec_id=task_spec.id,
            deterministic=det,
            llm_judgment=_judgment_from_payload(payload),
            metadata_citation_warnings=metadata_warnings,
            prompt_version=self._prompt_version,
        )


def _build_user_message(
    draft_text: str,
    *,
    task_spec: TaskSpecification,
    evidence_map: list[ResearchNote],
    det: DeterministicCheckResult,
    bibliography_candidates: list[str],
    source_cards: list[SourceCard],
    metadata_warnings: list[CitationMetadataWarning],
) -> str:
    context = {
        "task_spec": {
            "raw_text": task_spec.raw_text,
            "essay_type": task_spec.essay_type,
            "academic_level": task_spec.academic_level,
            "target_length": task_spec.target_length,
            "length_unit": task_spec.length_unit,
            "citation_style": task_spec.citation_style,
            "rubric": task_spec.rubric,
            "grading_criteria": task_spec.grading_criteria,
            "required_claims_or_questions": task_spec.required_claims_or_questions,
            "professor_constraints": task_spec.professor_constraints,
        },
        "evidence_map": [
            {
                "note_id": n.id,
                "source_id": n.source_id,
                "chunk_id": n.chunk_id,
                "page_start": n.page_start,
                "page_end": n.page_end,
                "claim": n.claim,
                "paraphrase": n.paraphrase,
                "quote": n.quote,
                "evidence_type": n.evidence_type,
            }
            for n in evidence_map
        ],
        "bibliography_candidates": bibliography_candidates,
        "known_source_metadata": source_metadata_context(source_cards),
        "metadata_citation_warnings": [
            {
                "source_id": warning.source_id,
                "description": warning.description,
                "severity": warning.severity,
            }
            for warning in metadata_warnings
        ],
        "deterministic_issues": {
            "em_dash_count": det.em_dash_count,
            "tier1_vocab_hits": [{"word": h.word, "count": h.count} for h in det.tier1_vocab_hits],
            "bad_conclusion_opener": det.bad_conclusion_opener,
            "participial_phrase_count": det.participial_phrase_count,
            "participial_phrase_rate_per_300_words": round(det.participial_phrase_rate, 2),
            "contrastive_negation_count": det.contrastive_negation_count,
            "signposting_hits": det.signposting_hits,
            "consecutive_similar_sentence_runs": len(det.consecutive_similar_sentence_runs),
        },
    }
    return (
        "Validate the essay draft below against the task specification, evidence map, and rubric.\n"
        "The deterministic_issues have already been identified — do not re-check them.\n\n"
        f"{json.dumps(context)}\n\n"
        f"<essay_draft>\n{draft_text}\n</essay_draft>"
    )


def _judgment_from_payload(payload: dict[str, Any]) -> LLMJudgmentResult:
    unsupported = [
        UnsupportedClaim(
            claim=str(item.get("claim", "")).strip(),
            paragraph=int(item.get("paragraph", 0)),
        )
        for item in payload.get("unsupported_claims", [])
        if str(item.get("claim", "")).strip()
    ]

    citation_issues = [
        CitationIssue(
            description=str(item.get("description", "")).strip(),
            severity=str(item.get("severity", "low")).strip(),
        )
        for item in payload.get("citation_issues", [])
        if str(item.get("description", "")).strip()
    ]

    rubric_scores = [
        RubricScore(
            criterion=str(item.get("criterion", "")).strip(),
            score=_bounded_float(item.get("score", 0.0)),
            note=str(item.get("note", "")).strip(),
        )
        for item in payload.get("rubric_scores", [])
        if str(item.get("criterion", "")).strip()
    ]

    fit_raw = payload.get("assignment_fit", {})
    assignment_fit = AssignmentFit(
        passes=bool(fit_raw.get("passes", False)),
        explanation=str(fit_raw.get("explanation", "")).strip(),
    )

    len_raw = payload.get("length_check", {})
    target = len_raw.get("target_words")
    length_check = LengthCheck(
        actual_words=int(len_raw.get("actual_words", 0)),
        target_words=int(target) if target is not None else None,
        passes=bool(len_raw.get("passes", True)),
    )

    style_issues = [
        StyleIssue(
            issue_type=str(item.get("issue_type", "other")).strip(),
            description=str(item.get("description", "")).strip(),
        )
        for item in payload.get("style_issues", [])
        if str(item.get("description", "")).strip()
    ]

    suggestions = [
        str(s).strip()
        for s in payload.get("revision_suggestions", [])
        if str(s).strip()
    ]

    return LLMJudgmentResult(
        unsupported_claims=unsupported,
        citation_issues=citation_issues,
        rubric_scores=rubric_scores,
        assignment_fit=assignment_fit,
        length_check=length_check,
        style_issues=style_issues,
        revision_suggestions=suggestions,
        overall_quality=_bounded_float(payload.get("overall_quality", 0.0)),
    )


def _bounded_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
