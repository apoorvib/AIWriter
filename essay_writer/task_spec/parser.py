from __future__ import annotations

import hashlib
import re
from typing import Any

from llm.client import LLMClient
from essay_writer.task_spec.prompts import (
    TASK_SPEC_SCHEMA,
    TASK_SPEC_SYSTEM_PROMPT,
    build_task_spec_user_message,
)
from essay_writer.task_spec.schema import (
    AdversarialFlag,
    ChecklistCategory,
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
            return self._baseline_parse(
                raw_text,
                task_id=task_id,
                version=version,
                source_document_ids=source_document_ids or [],
                selected_prompt=selected_prompt,
                adversarial_flags=deterministic_flags,
            )

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

    def _baseline_parse(
        self,
        raw_text: str,
        *,
        task_id: str | None,
        version: int,
        source_document_ids: list[str],
        selected_prompt: str | None,
        adversarial_flags: list[AdversarialFlag],
    ) -> TaskSpecification:
        checklist = _extract_baseline_checklist(raw_text, adversarial_flags)
        prompt_options = _extract_prompt_options(raw_text)
        blocking_questions: list[str] = []
        ambiguities: list[str] = []
        if len(prompt_options) > 1 and selected_prompt is None:
            question = "The assignment appears to list multiple prompt options. Which prompt should the essay answer?"
            blocking_questions.append(question)
            ambiguities.append(question)
        citation_style = _extract_citation_style(raw_text)
        target_length, length_unit = _extract_length(raw_text)
        nonblocking_warnings = [
            "Baseline deterministic task parsing was used; run LLM extraction before relying on subtle assignment constraints."
        ]
        if citation_style is None:
            nonblocking_warnings.append("Citation style was not clearly specified.")
        return TaskSpecification(
            id=task_id or _stable_task_id(raw_text),
            version=version,
            raw_text=raw_text,
            source_document_ids=source_document_ids,
            assignment_title=_extract_title(raw_text),
            target_length=target_length,
            length_unit=length_unit,
            citation_style=citation_style,
            prompt_options=prompt_options,
            selected_prompt=selected_prompt,
            adversarial_flags=adversarial_flags,
            ignored_ai_directives=[flag.source_span for flag in adversarial_flags],
            extracted_checklist=checklist,
            ambiguities=ambiguities,
            risk_flags=["adversarial_text_detected"] if adversarial_flags else [],
            blocking_questions=blocking_questions,
            nonblocking_warnings=nonblocking_warnings,
            confidence_by_field={
                "extracted_checklist": 0.45,
                "citation_style": 0.7 if citation_style else 0.0,
                "target_length": 0.8 if target_length else 0.0,
            },
            parser_version=self._parser_version,
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


def _extract_baseline_checklist(raw_text: str, adversarial_flags: list[AdversarialFlag]) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for line in _candidate_lines(raw_text):
        if _matches_adversarial_span(line, adversarial_flags):
            continue
        if not _looks_like_requirement(line):
            continue
        items.append(
            ChecklistItem(
                id=f"req_{len(items) + 1:03d}",
                text=line,
                category=_categorize_requirement(line),
                required=True,
                source_span=line,
                confidence=0.55,
            )
        )
    return items


def _candidate_lines(raw_text: str) -> list[str]:
    lines = []
    for raw_line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip(" \t-*").strip("\u2022").strip()
        if line:
            lines.append(line)
    return lines


def _looks_like_requirement(line: str) -> bool:
    lower = line.lower()
    keywords = [
        "must",
        "required",
        "requirement",
        "use ",
        "include",
        "cite",
        "write",
        "submit",
        "analyze",
        "compare",
        "argue",
        "thesis",
        "source",
        "format",
        "mla",
        "apa",
        "chicago",
        "words",
        "pages",
    ]
    return any(keyword in lower for keyword in keywords)


def _categorize_requirement(line: str) -> ChecklistCategory:
    lower = line.lower()
    if any(token in lower for token in ["source", "sources", "reading", "readings", "outside"]):
        return "source"
    if any(token in lower for token in ["mla", "apa", "chicago", "citation", "cite", "bibliography", "works cited"]):
        return "citation"
    if any(token in lower for token in ["paragraph", "introduction", "conclusion", "thesis", "counterargument", "structure"]):
        return "structure"
    if any(token in lower for token in ["font", "spacing", "format", "margin", "pages", "words"]):
        return "formatting"
    if any(token in lower for token in ["rubric", "grade", "points", "criteria"]):
        return "rubric"
    if any(token in lower for token in ["submit", "upload", "docx", "pdf"]):
        return "submission"
    if any(token in lower for token in ["tone", "first person", "style"]):
        return "style"
    if any(token in lower for token in ["question", "prompt", "topic"]):
        return "topic"
    return "content"


def _extract_prompt_options(raw_text: str) -> list[str]:
    options: list[str] = []
    pattern = re.compile(r"^\s*(?:prompt|option)?\s*([A-D]|\d+)[\).:-]\s+(.+)$", re.I)
    for line in raw_text.splitlines():
        match = pattern.match(line)
        if match:
            options.append(line.strip())
    return options


def _extract_citation_style(raw_text: str) -> str | None:
    lower = raw_text.lower()
    for style in ("MLA", "APA", "Chicago"):
        if style.lower() in lower:
            return style
    return None


def _extract_length(raw_text: str) -> tuple[int | None, str | None]:
    match = re.search(r"\b(\d{2,5})\s*(words|word|pages|page)\b", raw_text, re.I)
    if not match:
        return None, None
    return int(match.group(1)), match.group(2).lower()


def _extract_title(raw_text: str) -> str | None:
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return None


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
