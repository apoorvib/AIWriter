"""LLMClient protocol and shared types for the multi-provider shim."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMError(Exception):
    """Raised when an LLM call fails or returns malformed output."""


@runtime_checkable
class LLMClient(Protocol):
    """Minimal provider-agnostic JSON-output client.

    Implementations enforce structured JSON output using their provider's
    native mechanism (Anthropic tool-use, OpenAI response_format json_schema,
    Gemini response_schema). The returned dict must conform to json_schema.
    """

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any]: ...
