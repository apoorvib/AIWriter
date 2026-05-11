"""LLMClient protocol and shared types for the multi-provider shim."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

DEFAULT_LLM_MAX_OUTPUT_TOKENS = 16000


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class UserBlock:
    """A segment of a user message with an optional cache hint.

    Callers split user messages into segments so adapters that support prompt
    caching (Anthropic) can mark the static prefix as cacheable. Adapters that
    do not support per-segment caching (OpenAI's automatic prefix caching,
    Gemini, mocks) simply concatenate the segments.
    """

    text: str
    cacheable: bool = False


def normalize_user_content(content: "str | Iterable[UserBlock]") -> list[UserBlock]:
    """Normalize a user-content argument into a list of UserBlock segments."""
    if isinstance(content, str):
        return [UserBlock(text=content, cacheable=False)]
    return [block for block in content]


def concat_user_content(content: "str | Iterable[UserBlock]") -> str:
    """Flatten a user-content argument back to a single string.

    Used by adapters and clients (OpenAI, Gemini, mocks, logging) that do not
    distinguish between cached and uncached segments.
    """
    if isinstance(content, str):
        return content
    return "".join(block.text for block in content)


class LLMError(Exception):
    """Raised when an LLM call fails or returns malformed output."""


class LLMConfigurationError(LLMError):
    """Raised when an LLM-backed workflow step is invoked without an LLM client."""


@runtime_checkable
class LLMClient(Protocol):
    """Minimal provider-agnostic JSON-output client.

    Implementations enforce structured JSON output using their provider's
    native mechanism (Anthropic tool-use, OpenAI response_format json_schema,
    Gemini response_schema). The returned dict must conform to json_schema.

    user content may be either a string or a list of UserBlock segments. The
    list form lets callers mark the static prefix as cacheable for adapters
    that support prompt caching; adapters that do not concatenate the segments.
    """

    def chat_json(
        self,
        system: str,
        user: str | list[UserBlock],
        json_schema: dict[str, Any],
        max_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        model: str | None = None,
        enable_web_search: bool = False,
    ) -> dict[str, Any]: ...
