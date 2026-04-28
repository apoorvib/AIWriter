from __future__ import annotations

import os
from typing import Any

from llm.client import LLMClient
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.tone_alignment.prompts import (
    TONE_ALIGNMENT_SCHEMA,
    TONE_ALIGNMENT_SYSTEM_PROMPT,
    build_tone_alignment_user_message,
)
from essay_writer.tone_alignment.schema import ToneAlignmentConflict, ToneAlignmentReport
from essay_writer.validation.checks import run_deterministic_checks
from essay_writer.writing_style.schema import WritingStylePayload


DEFAULT_TONE_ALIGNMENT_MAX_TOKENS = 3000


class ToneAlignmentService:
    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_version: str = "tone-alignment-v1",
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> None:
        self._llm = llm_client
        self._prompt_version = prompt_version
        self._max_tokens = max_tokens or tone_alignment_max_tokens_from_env()
        self._model = model or tone_alignment_model_from_env()

    def evaluate(
        self,
        draft_text: str,
        *,
        draft_id: str,
        task_spec: TaskSpecification,
        writing_style_payload: WritingStylePayload,
        model: str | None = None,
    ) -> ToneAlignmentReport:
        det = run_deterministic_checks(draft_text)
        payload = self._llm.chat_json(
            system=TONE_ALIGNMENT_SYSTEM_PROMPT,
            user=build_tone_alignment_user_message(
                draft_text=draft_text,
                task_spec=task_spec,
                det=det,
                writing_style_payload=writing_style_payload,
            ),
            json_schema=TONE_ALIGNMENT_SCHEMA,
            max_tokens=self._max_tokens,
            model=model or self._model,
        )
        return ToneAlignmentReport(
            draft_id=draft_id,
            writing_style_content_id=writing_style_payload.style_content.id,
            overall_alignment=_bounded_float(payload.get("overall_alignment", 0.0)),
            requires_revision=bool(payload.get("requires_revision", False)),
            matched_habits=_payload_list(payload, "matched_habits", max_items=20),
            mismatched_habits=_payload_list(payload, "mismatched_habits", max_items=20),
            preserve_points=_payload_list(payload, "preserve_points", max_items=20),
            revision_targets=_payload_list(payload, "revision_targets", max_items=20),
            anti_ai_conflicts=[
                ToneAlignmentConflict(
                    issue_type=str(item.get("issue_type", "")).strip() or "other",
                    anti_ai_signal=str(item.get("anti_ai_signal", "")).strip(),
                    tone_signal=str(item.get("tone_signal", "")).strip(),
                    resolution=str(item.get("resolution", "")).strip() or "prefer_tone",
                    rationale=str(item.get("rationale", "")).strip(),
                )
                for item in payload.get("anti_ai_conflicts", [])
                if str(item.get("anti_ai_signal", "")).strip() or str(item.get("tone_signal", "")).strip()
            ],
            prompt_version=self._prompt_version,
        )


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value[:max_items] if str(item).strip()]


def _bounded_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def tone_alignment_model_from_env() -> str | None:
    return os.environ.get("ESSAY_MODEL_TONE_ALIGNMENT") or os.environ.get("LLM_MODEL") or None


def tone_alignment_max_tokens_from_env(default: int = DEFAULT_TONE_ALIGNMENT_MAX_TOKENS) -> int:
    value = os.environ.get("ESSAY_MAX_TOKENS_TONE_ALIGNMENT")
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
