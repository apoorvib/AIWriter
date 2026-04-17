"""Layer 2: LLM-driven TOC entry extraction with chunked, bounded scanning."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from llm.client import LLMClient
from pdf_pipeline.outline.prompts import (
    TOC_EXTRACTION_SCHEMA,
    TOC_SYSTEM_PROMPT,
    build_user_message,
)


@dataclass(frozen=True)
class RawEntry:
    title: str
    level: int
    printed_page: str


def extract_toc_entries(
    pages: list[dict[str, Any]],
    client: LLMClient,
    chunk_size: int = 5,
    max_tokens: int = 4096,
) -> list[RawEntry]:
    """Run chunked TOC extraction over the given pages.

    - Chunks the pages using ceil(len / chunk_size).
    - Stops at the first chunk containing zero TOC pages AFTER at least one
      TOC page has been seen in a prior chunk.
    - Returns the merged list of raw entries in chunk order.
    """
    if not pages:
        return []

    entries: list[RawEntry] = []
    seen_toc = False
    num_chunks = math.ceil(len(pages) / chunk_size)

    for i in range(num_chunks):
        chunk = pages[i * chunk_size : (i + 1) * chunk_size]
        response = client.chat_json(
            system=TOC_SYSTEM_PROMPT,
            user=build_user_message(chunk),
            json_schema=TOC_EXTRACTION_SCHEMA,
            max_tokens=max_tokens,
        )
        chunk_has_toc = any(p.get("is_toc") for p in response.get("pages", []))
        for raw in response.get("entries", []):
            entries.append(
                RawEntry(
                    title=str(raw["title"]),
                    level=int(raw["level"]),
                    printed_page=str(raw["printed_page"]),
                )
            )

        if chunk_has_toc:
            seen_toc = True

        if seen_toc and response.get("pages") and not response["pages"][-1].get("is_toc"):
            break

    return entries
