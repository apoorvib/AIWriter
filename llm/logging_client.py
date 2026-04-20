from __future__ import annotations

import logging
import time
from typing import Any

from llm.client import DEFAULT_LLM_MAX_OUTPUT_TOKENS

logger = logging.getLogger("essay_writer.llm")


class LoggingLLMClient:
    """Wraps any LLMClient and emits structured log lines around every call."""

    def __init__(self, inner: Any, *, stage: str = "unknown") -> None:
        self._inner = inner
        self._stage = stage

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        model: str | None = None,
        enable_web_search: bool = False,
    ) -> dict[str, Any]:
        logger.info(
            "llm.call.start stage=%s model=%s sys_chars=%d user_chars=%d max_tokens=%d web_search=%s",
            self._stage,
            model or "adapter-default",
            len(system),
            len(user),
            max_tokens,
            enable_web_search,
        )
        t0 = time.monotonic()
        try:
            result = self._inner.chat_json(
                system,
                user,
                json_schema,
                max_tokens,
                model=model,
                enable_web_search=enable_web_search,
            )
            elapsed = time.monotonic() - t0
            logger.info(
                "llm.call.done stage=%s elapsed_s=%.3f result_keys=%s",
                self._stage,
                elapsed,
                sorted(result.keys()),
            )
            return result
        except Exception:
            elapsed = time.monotonic() - t0
            logger.exception(
                "llm.call.error stage=%s elapsed_s=%.3f",
                self._stage,
                elapsed,
            )
            raise
