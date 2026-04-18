"""OpenAI adapter using chat completions with response_format=json_schema."""
from __future__ import annotations

import json
from typing import Any

from llm.client import LLMError


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
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> dict[str, Any]:
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
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"OpenAI returned invalid JSON: {exc}") from exc
