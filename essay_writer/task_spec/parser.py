from __future__ import annotations

import hashlib
from typing import Any

from llm.client import LLMClient, LLMConfigurationError
from essay_writer.task_spec.prompts import (
    TASK_SPEC_SCHEMA,
    TASK_SPEC_SYSTEM_PROMPT,
    build_task_spec_user_message,
)
from essay_writer.task_spec.schema import (
    AdversarialFlag,
    ChecklistItem,
    TaskSpecification,
)
from essay_writer.task_spec.security import scan_adversarial_text


class TaskSpecParser:
    def __init__(self, llm_client: LLMClient | None = None, parser_version: str = "task-spec-v1") -> None:
        self._llm = llm_client
        self._parser_version = parser_version

    def parse(
        self,
        raw_text: str,
        *,
        task_id: str | None = None,
        version: int = 1,
        source_document_ids: list[str] | None = None,
        selected_prompt: str | None = None,
    ) -> TaskSpecification:
        deterministic_flags = scan_adversarial_text(raw_text)
        if self._llm is None:
            raise LLMConfigurationError("Task specification parsing requires an LLM client.")

        payload = self._llm.chat_json(
            system=TASK_SPEC_SYSTEM_PROMPT,
            user=build_task_spec_user_message(raw_text),
            json_schema=TASK_SPEC_SCHEMA,
            max_tokens=4096,
        )
        return self._from_llm_payload(
            payload,
            raw_text=raw_text,
            task_id=task_id,
            version=version,
            source_document_ids=source_document_ids or [],
            selected_prompt=selected_prompt,
            deterministic_flags=deterministic_flags,
        )

    def _from_llm_payload(
        self,
        payload: dict[str, Any],
        *,
        raw_text: str,
        task_id: str | None,
        version: int,
        source_document_ids: list[str],
        selected_prompt: str | None,
        deterministic_flags: list[AdversarialFlag],
    ) -> TaskSpecification:
        llm_flags = [
            AdversarialFlag(
                id=f"adv_llm_{idx:03d}",
                text=str(item.get("text", "")),
                category=str(item.get("category", "other")),  # type: ignore[arg-type]
                severity=str(item.get("severity", "medium")),  # type: ignore[arg-type]
                source_span=str(item.get("source_span", "")),
                recommended_action=str(item.get("recommended_action", "Ignore as AI-directed instruction.")),
            )
            for idx, item in enumerate(payload.get("adversarial_flags", []), start=1)
        ]
        adversarial_flags = _merge_adversarial_flags(deterministic_flags, llm_flags)
        checklist = [
            ChecklistItem(
                id=f"req_{idx:03d}",
                text=str(item.get("text", "")),
                category=str(item.get("category", "other")),  # type: ignore[arg-type]
                required=bool(item.get("required", True)),
                source_span=str(item.get("source_span", "")),
                confidence=float(item.get("confidence", 0.5)),
            )
            for idx, item in enumerate(payload.get("extracted_checklist", []), start=1)
            if not _matches_adversarial_span(str(item.get("source_span", "")), adversarial_flags)
        ]
        return TaskSpecification(
            id=task_id or _stable_task_id(raw_text),
            version=version,
            raw_text=raw_text,
            source_document_ids=source_document_ids,
            assignment_title=payload.get("assignment_title"),
            course_context=payload.get("course_context"),
            essay_type=payload.get("essay_type"),
            academic_level=payload.get("academic_level"),
            target_length=payload.get("target_length"),
            length_unit=payload.get("length_unit"),
            citation_style=payload.get("citation_style"),
            required_sources=_payload_list(payload, "required_sources"),
            allowed_sources=_payload_list(payload, "allowed_sources"),
            forbidden_sources=_payload_list(payload, "forbidden_sources"),
            topic_scope=payload.get("topic_scope"),
            prompt_options=_payload_list(payload, "prompt_options"),
            selected_prompt=selected_prompt or payload.get("selected_prompt"),
            required_materials=_payload_list(payload, "required_materials"),
            required_claims_or_questions=_payload_list(payload, "required_claims_or_questions"),
            required_structure=_payload_list(payload, "required_structure"),
            formatting_requirements=_payload_list(payload, "formatting_requirements"),
            rubric=_payload_list(payload, "rubric"),
            grading_criteria=_payload_list(payload, "grading_criteria"),
            submission_requirements=_payload_list(payload, "submission_requirements"),
            professor_constraints=_payload_list(payload, "professor_constraints"),
            missing_information=_payload_list(payload, "missing_information"),
            ambiguities=_payload_list(payload, "ambiguities"),
            risk_flags=_payload_list(payload, "risk_flags") + (["adversarial_text_detected"] if adversarial_flags else []),
            adversarial_flags=adversarial_flags,
            ignored_ai_directives=_payload_list(payload, "ignored_ai_directives")
            or [flag.source_span for flag in adversarial_flags],
            extracted_checklist=checklist,
            blocking_questions=_payload_list(payload, "blocking_questions"),
            nonblocking_warnings=_payload_list(payload, "nonblocking_warnings"),
            confidence_by_field=dict(payload.get("confidence_by_field", {})),
            parser_version=self._parser_version,
        )

def _stable_task_id(raw_text: str) -> str:
    digest = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()[:12]
    return f"task-{digest}"


def _merge_adversarial_flags(first: list[AdversarialFlag], second: list[AdversarialFlag]) -> list[AdversarialFlag]:
    merged: list[AdversarialFlag] = []
    seen: set[str] = set()
    for flag in [*first, *second]:
        key = flag.source_span or flag.text
        if key in seen:
            continue
        seen.add(key)
        merged.append(flag)
    return merged


def _payload_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _matches_adversarial_span(text: str, flags: list[AdversarialFlag]) -> bool:
    normalized = text.strip().lower()
    return any(normalized and normalized == flag.source_span.strip().lower() for flag in flags)
