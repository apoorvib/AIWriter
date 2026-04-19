"""Gemini adapter using generate_content with response_schema."""
from __future__ import annotations

import json
from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS, LLMError


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
    ) -> dict[str, Any]:
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
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini returned invalid JSON: {exc}") from exc
