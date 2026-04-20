"""OpenAI adapter using chat completions with response_format=json_schema."""
from __future__ import annotations

import json
import logging
from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS, LLMError

logger = logging.getLogger("essay_writer.llm")


class OpenAIClient:
    """LLMClient implementation backed by OpenAI's chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-2024-11-20",
        sdk: Any = None,
    ) -> None:
        if sdk is not None:
            self._sdk = sdk
        else:
            import openai
            self._sdk = openai.OpenAI(api_key=api_key)
        self._model = model

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
            raise NotImplementedError("enable_web_search is not yet supported for OpenAI")
        response = self._sdk.chat.completions.create(
            model=model or self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "schema": json_schema,
                    "strict": True,
                },
            },
        )
        self._log_usage(response)
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"OpenAI returned invalid JSON: {exc}") from exc

    def _log_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        if input_tokens is not None and output_tokens is not None:
            logger.debug(
                "llm.usage provider=openai input_tokens=%d output_tokens=%d",
                input_tokens,
                output_tokens,
            )
