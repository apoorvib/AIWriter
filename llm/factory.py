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

    Optional `LLM_MODEL` sets the default model id for the chosen provider
    (same ids accepted by each adapter's constructor).

    Raises:
        ValueError: if the provider name is not recognized.
        KeyError: if the required API key env var is not set.
    """
    name = (provider or os.environ.get("LLM_PROVIDER", "claude")).lower()
    model = os.environ.get("LLM_MODEL")

    if name == "claude":
        from llm.adapters.claude import ClaudeClient
        return ClaudeClient(
            api_key=_require_env("ANTHROPIC_API_KEY", name),
            **({"model": model} if model else {}),
        )
    if name == "openai":
        from llm.adapters.openai_ import OpenAIClient
        return OpenAIClient(
            api_key=_require_env("OPENAI_API_KEY", name),
            **({"model": model} if model else {}),
        )
    if name == "gemini":
        from llm.adapters.gemini import GeminiClient
        return GeminiClient(
            api_key=_require_env("GEMINI_API_KEY", name),
            **({"model_name": model} if model else {}),
        )
    raise ValueError(f"unknown provider: {name}")


def _require_env(var: str, provider: str) -> str:
    try:
        return os.environ[var]
    except KeyError:
        raise KeyError(
            f"{var} environment variable is not set; "
            f"required by the {provider!r} LLM provider"
        ) from None
