from __future__ import annotations

from typing import Any

from llm.client import LLMClient
from essay_writer.sources.schema import SourceCard, SourceIndexManifest
from essay_writer.sources.access_schema import SourceLocator, SourceMap, locator_from_payload
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.context import build_topic_ideation_context
from essay_writer.topic_ideation.prompts import TOPIC_IDEATION_SCHEMA, TOPIC_IDEATION_SYSTEM_PROMPT
from essay_writer.topic_ideation.schema import CandidateTopic, RejectedTopic, TopicIdeationResult, TopicSourceLead


class TopicIdeationService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "topic-ideation-v1",
        max_candidates: int = 8,
    ) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        self._llm = llm_client
        self._prompt_version = prompt_version
        self._max_candidates = max_candidates

    def generate(
        self,
        task_spec: TaskSpecification,
        *,
        source_cards: list[SourceCard],
        index_manifests: list[SourceIndexManifest] | None = None,
        source_maps: list[SourceMap] | None = None,
        previous_candidates: list[CandidateTopic] | None = None,
        rejected_topics: list[RejectedTopic] | None = None,
        user_instruction: str | None = None,
        model: str | None = None,
    ) -> TopicIdeationResult:
        context = build_topic_ideation_context(
            task_spec,
            source_cards=source_cards,
            index_manifests=index_manifests or [],
            source_maps=source_maps or [],
            previous_candidates=previous_candidates or [],
            rejected_topics=rejected_topics or [],
            user_instruction=user_instruction,
            max_manifest_entries=80,
        )
        payload = self._llm.chat_json(
            system=TOPIC_IDEATION_SYSTEM_PROMPT,
            user=_build_user_message(context, self._max_candidates),
            json_schema=TOPIC_IDEATION_SCHEMA,
            max_tokens=5000,
            model=model,
        )
        return _result_from_payload(
            task_spec_id=task_spec.id,
            payload=payload,
            prompt_version=self._prompt_version,
            max_candidates=self._max_candidates,
        )


def _build_user_message(context: str, max_candidates: int) -> str:
    return (
        f"Generate up to {max_candidates} candidate essay topics.\n"
        "Return only topics that fit the assignment and can plausibly be supported by the uploaded sources.\n"
        "If previous_candidates are present, avoid duplicates and use parent_topic_id only when refining a prior topic.\n"
        "If rejected_topics are present, avoid repeating those directions and honor the rejection reasons.\n"
        "If user_instruction is present, treat it as direction for this new round without overriding assignment requirements.\n"
        "Use chunk_ids from the manifests when possible and suggested_source_search_queries for uploaded-source retrieval.\n"
        "Prefer source_requests from source maps: use physical PDF page numbers for PDFs and section IDs for non-PDF sources.\n"
        "Do not include external web or database search queries in this stage.\n\n"
        f"{context}"
    )


def _result_from_payload(
    *,
    task_spec_id: str,
    payload: dict[str, Any],
    prompt_version: str,
    max_candidates: int,
) -> TopicIdeationResult:
    candidates = [
        CandidateTopic(
            id=f"topic_{idx:03d}",
            title=str(item.get("title", "")).strip(),
            research_question=str(item.get("research_question", "")).strip(),
            tentative_thesis_direction=str(item.get("tentative_thesis_direction", "")).strip(),
            rationale=str(item.get("rationale", "")).strip(),
            parent_topic_id=_optional_str(item.get("parent_topic_id")),
            novelty_note=_optional_str(item.get("novelty_note")),
            source_leads=[
                TopicSourceLead(
                    source_id=str(lead.get("source_id", "")).strip(),
                    chunk_ids=_payload_list(lead, "chunk_ids", max_items=20),
                    suggested_source_search_queries=_payload_list(
                        lead,
                        "suggested_source_search_queries",
                        max_items=10,
                    ),
                )
                for lead in item.get("source_leads", [])
                if str(lead.get("source_id", "")).strip()
            ],
            source_requests=_source_requests_from_payload(item.get("source_requests", []), max_items=20),
            fit_score=_bounded_float(item.get("fit_score", 0.0)),
            evidence_score=_bounded_float(item.get("evidence_score", 0.0)),
            originality_score=_bounded_float(item.get("originality_score", 0.0)),
            risk_flags=_payload_list(item, "risk_flags", max_items=10),
            missing_evidence=_payload_list(item, "missing_evidence", max_items=10),
        )
        for idx, item in enumerate(payload.get("candidates", [])[:max_candidates], start=1)
    ]
    return TopicIdeationResult(
        task_spec_id=task_spec_id,
        candidates=candidates,
        blocking_questions=_payload_list(payload, "blocking_questions", max_items=10),
        warnings=_payload_list(payload, "warnings", max_items=10),
        prompt_version=prompt_version,
    )


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value[:max_items] if str(item).strip()]


def _source_requests_from_payload(value: Any, *, max_items: int) -> list[SourceLocator]:
    if not isinstance(value, list):
        return []
    locators: list[SourceLocator] = []
    for item in value[:max_items]:
        if not isinstance(item, dict):
            continue
        locator = locator_from_payload(item)
        if locator.source_id and locator.locator_type in {"pdf_pages", "section", "search", "chunk"}:
            locators.append(locator)
    return locators


def _bounded_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
