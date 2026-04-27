from __future__ import annotations

import hashlib
import os
from typing import Any

from llm.client import LLMClient, LLMConfigurationError
from essay_writer.writing_style.prompts import (
    WRITING_STYLE_CONTENT_SCHEMA,
    WRITING_STYLE_CONTENT_SYSTEM_PROMPT,
    build_writing_style_prompt_block,
    build_writing_style_user_message,
)
from essay_writer.writing_style.schema import (
    PromptSampleText,
    StyleAnchorExcerpt,
    WritingStyleContent,
    WritingStylePayload,
)
from essay_writer.writing_style.storage import stable_writing_style_content_id


DEFAULT_WRITING_STYLE_MAX_TOKENS = 4000


class WritingStyleContentService:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        generator_version: str = "writing-style-content-v1",
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> None:
        self._llm = llm_client
        self._generator_version = generator_version
        self._max_tokens = max_tokens or writing_style_max_tokens_from_env()
        self._model = model or writing_style_model_from_env()

    def generate(
        self,
        samples: list[PromptSampleText],
        *,
        content_id: str | None = None,
        version: int = 1,
        model: str | None = None,
    ) -> WritingStyleContent:
        if not samples:
            raise ValueError("At least one writing sample is required.")
        if self._llm is None:
            raise LLMConfigurationError("Writing style analysis requires an LLM client.")
        payload = self._llm.chat_json(
            system=WRITING_STYLE_CONTENT_SYSTEM_PROMPT,
            user=build_writing_style_user_message(samples),
            json_schema=WRITING_STYLE_CONTENT_SCHEMA,
            max_tokens=self._max_tokens,
            model=model or self._model,
        )
        sample_fingerprint = build_sample_fingerprint(
            samples,
            generator_version=self._generator_version,
        )
        return _content_from_payload(
            payload,
            sample_ids=[sample.sample_id for sample in samples],
            sample_fingerprint=sample_fingerprint,
            version=version,
            content_id=content_id or stable_writing_style_content_id(sample_fingerprint),
            generator_model=model or self._model,
            generator_version=self._generator_version,
        )


def writing_style_model_from_env() -> str | None:
    return os.environ.get("ESSAY_MODEL_WRITING_STYLE") or os.environ.get("LLM_MODEL") or None


def writing_style_max_tokens_from_env(default: int = DEFAULT_WRITING_STYLE_MAX_TOKENS) -> int:
    value = os.environ.get("ESSAY_MAX_TOKENS_WRITING_STYLE")
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def build_sample_fingerprint(
    samples: list[PromptSampleText],
    *,
    generator_version: str,
) -> str:
    material = "||".join(
        f"{sample.sample_id}:{sample.cleaned_text_hash}"
        for sample in sorted(samples, key=lambda item: item.sample_id)
    )
    material = f"{generator_version}||{material}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def build_writing_style_payload(
    content: WritingStyleContent,
    samples: list[PromptSampleText],
) -> WritingStylePayload:
    selected = {sample_id for sample_id in content.sample_ids}
    return WritingStylePayload(
        style_content=content,
        samples=[sample for sample in samples if sample.sample_id in selected],
    )


def render_writing_style_prompt_block(
    content: WritingStyleContent,
    samples: list[PromptSampleText],
) -> str:
    return build_writing_style_prompt_block(build_writing_style_payload(content, samples))


def _content_from_payload(
    payload: dict[str, Any],
    *,
    sample_ids: list[str],
    sample_fingerprint: str,
    version: int,
    content_id: str,
    generator_model: str | None,
    generator_version: str,
) -> WritingStyleContent:
    return WritingStyleContent(
        id=content_id,
        version=version,
        sample_ids=sample_ids,
        sample_fingerprint=sample_fingerprint,
        guidance=_payload_list(payload, "guidance", max_items=12),
        preferred_moves=_payload_list(payload, "preferred_moves", max_items=12),
        avoid_moves=_payload_list(payload, "avoid_moves", max_items=12),
        lexical_habits=_payload_list(payload, "lexical_habits", max_items=12),
        structural_habits=_payload_list(payload, "structural_habits", max_items=12),
        anchor_excerpts=[
            StyleAnchorExcerpt(
                sample_id=str(item.get("sample_id", "")).strip(),
                excerpt_id=str(item.get("excerpt_id", "")).strip() or f"excerpt_{idx:02d}",
                text=str(item.get("text", "")).strip(),
                role=str(item.get("role", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
            for idx, item in enumerate(payload.get("anchor_excerpts", []), start=1)
            if str(item.get("text", "")).strip()
        ],
        warnings=_payload_list(payload, "warnings", max_items=12),
        generator_model=generator_model,
        generator_version=generator_version,
    )


def _payload_list(payload: dict[str, Any], key: str, *, max_items: int) -> list[str]:
    value = payload.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value[:max_items] if str(item).strip()]

