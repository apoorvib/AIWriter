"""Gemini adapter using generate_content with response_schema."""
from __future__ import annotations

import json
import logging
from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS, LLMError

logger = logging.getLogger("essay_writer.llm")


class GeminiClient:
    """LLMClient implementation backed by Google's generative AI SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-pro",
        model_obj: Any = None,
    ) -> None:
        if model_obj is not None:
            self._model = model_obj
        else:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(model_name)
        self._model_name = model_name

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        model: str | None = None,
        enable_web_search: bool = False,
    ) -> dict[str, Any]:
        if enable_web_search:
            raise NotImplementedError("enable_web_search is not yet supported for Gemini")
        combined = f"{system}\n\n{user}"
        gen_model = self._model
        if model is not None and model != self._model_name:
            import google.generativeai as genai
            gen_model = genai.GenerativeModel(model)
        response = gen_model.generate_content(
            [combined],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": json_schema,
                "max_output_tokens": max_tokens,
            },
        )
        self._log_usage(response)
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini returned invalid JSON: {exc}") from exc

    def _log_usage(self, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "prompt_token_count", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        if input_tokens is not None and output_tokens is not None:
            logger.debug(
                "llm.usage provider=gemini input_tokens=%d output_tokens=%d",
                input_tokens,
                output_tokens,
            )
