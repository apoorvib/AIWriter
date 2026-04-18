"""In-memory LLMClient for tests."""
from __future__ import annotations

from typing import Any


class MockLLMClient:
    """LLMClient stand-in that returns queued responses and records calls."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses: list[dict[str, Any]] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "json_schema": json_schema,
                "max_tokens": max_tokens,
                "model": model,
            }
        )
        if not self._responses:
            raise RuntimeError("MockLLMClient ran out of responses")
        return self._responses.pop(0)
