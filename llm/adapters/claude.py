"""Claude adapter using Anthropic tool-use for JSON output."""
from __future__ import annotations

from typing import Any

from llm.client import LLMError


class ClaudeClient:
    """LLMClient implementation backed by Anthropic's messages API.

    JSON structured output is enforced by declaring a single tool with the
    required schema and forcing the model to call it.
    """

    _TOOL_NAME = "return_result"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-opus-4-7",
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
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        response = self._sdk.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": self._TOOL_NAME,
                    "description": "Return the structured result.",
                    "input_schema": json_schema,
                }
            ],
            tool_choice={"type": "tool", "name": self._TOOL_NAME},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == self._TOOL_NAME:
                return dict(block.input)
        raise LLMError("Claude response contained no tool_use block")
