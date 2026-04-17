"""Environment-driven factory for selecting an LLMClient implementation."""
from __future__ import annotations

import os

from llm.client import LLMClient


def make_client(provider: str | None = None) -> LLMClient:
    """Return an LLMClient for the given provider.

    Provider is selected in this order:
    1. Explicit `provider` argument.
    2. `LLM_PROVIDER` environment variable.
    3. Defaults to "claude".

    Raises:
        ValueError: if the provider name is not recognized.
        KeyError: if the required API key env var is not set.
    """
    name = (provider or os.environ.get("LLM_PROVIDER", "claude")).lower()

    if name == "claude":
        from llm.adapters.claude import ClaudeClient
        return ClaudeClient(api_key=os.environ["ANTHROPIC_API_KEY"])
    if name == "openai":
        from llm.adapters.openai_ import OpenAIClient
        return OpenAIClient(api_key=os.environ["OPENAI_API_KEY"])
    if name == "gemini":
        from llm.adapters.gemini import GeminiClient
        return GeminiClient(api_key=os.environ["GEMINI_API_KEY"])
    raise ValueError(f"unknown provider: {name}")
