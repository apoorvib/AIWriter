"""Claude adapter using Anthropic tool-use for JSON output."""
from __future__ import annotations

import logging
from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS, LLMError, UserBlock, normalize_user_content

logger = logging.getLogger("essay_writer.llm")

_WEB_SEARCH_TOOL = {"type": "web_search_tool_20250305"}

# Conservative char-based gate for prompt caching. Anthropic's minimum cacheable
# token count is 2048 for Haiku (the default model) and 1024 for Sonnet/Opus.
# At ~3 chars/token, 6000 chars comfortably clears the Haiku floor without
# wasting the 1.25x write surcharge on small prompts.
_CACHE_MIN_CHARS = 6000


class ClaudeClient:
    """LLMClient implementation backed by Anthropic's messages API.

    JSON structured output is enforced by declaring a single tool with the
    required schema and forcing the model to call it. When enable_web_search
    is True, Anthropic's server-side web search tool is added and tool_choice
    is relaxed to auto so the model may search before returning the result.

    Large system prompts are automatically wrapped in a content-block list with
    cache_control=ephemeral so reused prompts (e.g. drafting + revision sharing
    the anti-AI skill document) hit Anthropic's prompt cache. Callers may also
    pass user content as a list of UserBlock segments, marking the static
    prefix as cacheable so revision passes within the 5-minute TTL pay 0.1x
    input cost on the shared context.
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
        user: str | list[UserBlock],
        json_schema: dict[str, Any],
        max_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        model: str | None = None,
        enable_web_search: bool = False,
    ) -> dict[str, Any]:
        result_tool = {
            "name": self._TOOL_NAME,
            "description": "Return the structured result.",
            "input_schema": json_schema,
        }
        if enable_web_search:
            tools: list[dict[str, Any]] = [_WEB_SEARCH_TOOL, result_tool]
            tool_choice: dict[str, Any] = {"type": "auto"}
        else:
            tools = [result_tool]
            tool_choice = {"type": "tool", "name": self._TOOL_NAME}

        params = {
            "model": model or self._model,
            "max_tokens": max_tokens,
            "system": _system_param(system),
            "messages": [{"role": "user", "content": _user_content_param(user)}],
            "tools": tools,
            "tool_choice": tool_choice,
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
        self._log_usage(response)
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

    def _log_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        if input_tokens is not None and output_tokens is not None:
            logger.debug(
                "llm.usage provider=claude input_tokens=%d output_tokens=%d "
                "cache_write_tokens=%d cache_read_tokens=%d",
                input_tokens,
                output_tokens,
                cache_write,
                cache_read,
            )


def _system_param(system: str) -> str | list[dict[str, Any]]:
    """Wrap large system prompts in a cache-controlled content block.

    Small prompts stay as plain strings to (a) avoid the 1.25x write surcharge
    for content that won't qualify as a cache entry and (b) preserve the
    pre-existing call shape for adapters and tests that assert on it.
    """
    if len(system) < _CACHE_MIN_CHARS:
        return system
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _user_content_param(user: str | list[UserBlock]) -> str | list[dict[str, Any]]:
    """Translate caller-provided user content to Anthropic block form.

    Strings pass through unchanged. A list of UserBlock segments emits one
    text block per segment; cacheable segments above the size floor receive
    cache_control=ephemeral. We cap at 4 cache breakpoints (Anthropic limit)
    by promoting only the last cacheable block when more would be requested.
    """
    if isinstance(user, str):
        return user
    blocks = list(normalize_user_content(user))
    rendered: list[dict[str, Any]] = []
    cacheable_indexes = [
        idx for idx, block in enumerate(blocks)
        if block.cacheable and len(block.text) >= _CACHE_MIN_CHARS
    ]
    # Anthropic supports up to 4 cache breakpoints per request total. The
    # system prompt may have already used one; reserve headroom by capping
    # user-side breakpoints at 3.
    keep_indexes = set(cacheable_indexes[-3:])
    for idx, block in enumerate(blocks):
        entry: dict[str, Any] = {"type": "text", "text": block.text}
        if idx in keep_indexes:
            entry["cache_control"] = {"type": "ephemeral"}
        rendered.append(entry)
    return rendered
