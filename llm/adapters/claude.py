"""Claude adapter using Anthropic tool-use for JSON output."""
from __future__ import annotations

from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS, LLMError


class ClaudeClient:
    """LLMClient implementation backed by Anthropic's messages API.

    JSON structured output is enforced by declaring a single tool with the
    required schema and forcing the model to call it.
    """

    _TOOL_NAME = "return_result"
    _STREAMING_TOKEN_THRESHOLD = 20000

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
        sdk: Any = None,
    ) -> None:
        if sdk is not None:
            self._sdk = sdk
        else:
            import anthropic
            self._sdk = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        model: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "model": model or self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": self._TOOL_NAME,
                    "description": "Return the structured result.",
                    "input_schema": json_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": self._TOOL_NAME},
        }
        if max_tokens > self._STREAMING_TOKEN_THRESHOLD:
            response = self._create_streaming_message(params)
        else:
            try:
                response = self._sdk.messages.create(**params)
            except ValueError as exc:
                if "Streaming is required" not in str(exc):
                    raise
                response = self._create_streaming_message(params)
        return self._extract_tool_input(response)

    def _create_streaming_message(self, params: dict[str, Any]) -> Any:
        with self._sdk.messages.stream(**params) as stream:
            stream.until_done()
            return stream.get_final_message()

    def _extract_tool_input(self, response: Any) -> dict[str, Any]:
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == self._TOOL_NAME:
                return dict(block.input)
        raise LLMError("Claude response contained no tool_use block")
