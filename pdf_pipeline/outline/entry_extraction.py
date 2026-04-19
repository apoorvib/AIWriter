"""Layer 2: LLM-driven TOC entry extraction with chunked, bounded scanning."""
from __future__ import annotations

import json
import math
import logging
from dataclasses import dataclass
from typing import Any

from llm.client import LLMClient
from pdf_pipeline.outline.prompts import (
    TOC_EXTRACTION_SCHEMA,
    TOC_SYSTEM_PROMPT,
    build_user_message,
)

logger = logging.getLogger(__name__)

TOC_LLM_MAX_OUTPUT_TOKENS = 64000


@dataclass(frozen=True)
class RawEntry:
    title: str
    level: int
    printed_page: str | None
    source_pdf_page: int | None = None


def extract_toc_entries(
    pages: list[dict[str, Any]],
    client: LLMClient,
    chunk_size: int = 5,
    max_tokens: int = TOC_LLM_MAX_OUTPUT_TOKENS,
    model: str | None = None,
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
        logger.info(
            "Layer 2 LLM chunk %d/%d: pages %s",
            i + 1,
            num_chunks,
            [page.get("pdf_page") for page in chunk],
        )
        response = client.chat_json(
            system=TOC_SYSTEM_PROMPT,
            user=build_user_message(chunk),
            json_schema=TOC_EXTRACTION_SCHEMA,
            max_tokens=max_tokens,
            model=model,
        )
        response_pages = response.get("pages", [])
        chunk_has_toc = any(p.get("is_toc") for p in response_pages)
        chunk_entries = _extract_response_entries(response)
        logger.info(
            "Layer 2 LLM chunk %d/%d: is_toc=%s entries=%d",
            i + 1,
            num_chunks,
            chunk_has_toc,
            len(chunk_entries),
        )
        if chunk_has_toc and not chunk_entries:
            logger.info(
                "Layer 2 LLM chunk %d/%d: TOC detected but no entries; response keys=%s page_keys=%s",
                i + 1,
                num_chunks,
                sorted(response.keys()),
                _page_key_summary(response_pages),
            )
        for raw in chunk_entries:
            entry = _coerce_raw_entry(raw)
            if entry is not None:
                entries.append(entry)

        if chunk_has_toc:
            seen_toc = True

        if seen_toc and response.get("pages") and not response["pages"][-1].get("is_toc"):
            break

    return entries


def _extract_response_entries(response: dict[str, Any]) -> list[dict[str, Any]]:
    top_level = _coerce_entry_list(response.get("entries", []), source="top-level entries")
    if top_level:
        return top_level

    # Defensive recovery: some models may put extracted entries on each page
    # despite the schema requiring top-level entries.
    nested: list[dict[str, Any]] = []
    for page in response.get("pages", []):
        if not isinstance(page, dict):
            continue
        for key in ("entries", "toc_entries"):
            nested.extend(
                _coerce_entry_list(
                    page.get(key, []),
                    source=f"page {page.get('pdf_page')} {key}",
                )
            )
    if nested:
        logger.info("Layer 2 LLM response: recovered %d nested page entries", len(nested))
    return nested


def _coerce_entry_list(value: Any, *, source: str) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            logger.warning(
                "Layer 2 LLM response: ignoring malformed %s string of length %d",
                source,
                len(value),
            )
            return []
    if isinstance(value, dict):
        value = value.get("entries", [])
    if not isinstance(value, list):
        logger.warning(
            "Layer 2 LLM response: ignoring malformed %s of type %s",
            source,
            type(value).__name__,
        )
        return []

    entries = [item for item in value if isinstance(item, dict)]
    skipped = len(value) - len(entries)
    if skipped:
        logger.warning(
            "Layer 2 LLM response: ignored %d non-object item(s) in %s",
            skipped,
            source,
        )
    return entries


def _coerce_raw_entry(raw: dict[str, Any]) -> RawEntry | None:
    try:
        title = str(raw["title"]).strip()
        level = int(raw["level"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Layer 2 LLM response: skipping malformed entry %r (%s)", raw, exc)
        return None
    printed_page_value = raw.get("printed_page")
    printed_page = (
        str(printed_page_value).strip()
        if printed_page_value is not None and str(printed_page_value).strip()
        else None
    )
    if not title or level < 1:
        logger.warning("Layer 2 LLM response: skipping incomplete entry %r", raw)
        return None
    return RawEntry(
        title=title,
        level=level,
        printed_page=printed_page,
        source_pdf_page=_coerce_optional_int(raw.get("source_pdf_page")),
    )


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_key_summary(pages: Any) -> list[list[str]]:
    if not isinstance(pages, list):
        return []
    summary: list[list[str]] = []
    for page in pages[:5]:
        if isinstance(page, dict):
            summary.append(sorted(str(key) for key in page.keys()))
    return summary
