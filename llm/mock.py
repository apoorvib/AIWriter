"""In-memory LLMClient for tests."""
from __future__ import annotations

from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS, UserBlock, concat_user_content, normalize_user_content


class MockLLMClient:
    """LLMClient stand-in that returns queued responses and records calls.

    The recorded call's `user` key is always a flat string so existing tests
    that assert on substring presence continue to work. When the caller passed
    structured UserBlock segments, the original blocks are also preserved
    under `user_blocks` for tests that need to verify cache-control intent.
    """

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses: list[dict[str, Any]] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat_json(
        self,
        system: str,
        user: str | list[UserBlock],
        json_schema: dict[str, Any],
        max_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        model: str | None = None,
        enable_web_search: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "system": system,
                "user": concat_user_content(user),
                "user_blocks": normalize_user_content(user),
                "json_schema": json_schema,
                "max_tokens": max_tokens,
                "model": model,
                "enable_web_search": enable_web_search,
            }
        )
        if not self._responses:
            raise RuntimeError("MockLLMClient ran out of responses")
        return self._responses.pop(0)
