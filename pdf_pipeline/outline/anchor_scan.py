"""Layer 3: deterministic offset resolution via anchor scan."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from pdf_pipeline.outline.entry_extraction import RawEntry

_CHAPTER_TOKEN = re.compile(r"\b(chapter|part|section|book)\s*\d+", re.IGNORECASE)


def _score_anchor(entry: RawEntry) -> int:
    """Higher is more distinctive."""
    words = entry.title.split()
    score = len(words)
    if _CHAPTER_TOKEN.search(entry.title):
        score += 5
    if len(words) < 3:
        score -= 5
    return score


def pick_anchor_candidates(entries: list[RawEntry], k: int = 3) -> list[RawEntry]:
    """Return up to k distinctive TOC entries to use as offset anchors.

    Selection heuristics: prefer longer titles with chapter/part/section
    tokens, drop duplicate titles, skip very short titles.
    """
    if not entries:
        return []

    seen_titles: set[str] = set()
    deduped: list[RawEntry] = []
    for e in entries:
        key = e.title.strip().lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(e)

    ranked = sorted(deduped, key=_score_anchor, reverse=True)
    return ranked[:k]


@dataclass(frozen=True)
class MatchResult:
    pdf_page: int
    pass_: Literal["A", "B"]


_FUZZY_THRESHOLD_DEFAULT = 80


def is_heading_like(page_text: str, title: str) -> bool:
    """Return True if `title` appears as a heading on the page.

    Heuristic signals: title sits on its own line within the first 6 lines
    of the page, and that line is shorter than 1.5x the title length (ruling
    out matches embedded inside prose).
    """
    if not page_text or not title:
        return False
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    for line in lines[:6]:
        if fuzz.partial_ratio(line.lower(), title.lower()) >= _FUZZY_THRESHOLD_DEFAULT:
            if len(line) <= int(len(title) * 1.5) + 5:
                return True
    return False


def find_anchor_page(
    anchor: RawEntry,
    pages_text: dict[int, str],
    max_offset: int = 100,
    fuzzy_threshold: int = _FUZZY_THRESHOLD_DEFAULT,
) -> MatchResult | None:
    """Scan forward from `anchor.printed_page` to find the anchor's pdf_page.

    Two-pass matching:
    - Pass A: prefer pages where the title appears as a heading-like line.
    - Pass B: fall back to the first fuzzy match anywhere on any page.

    Returns None if no match is found within max_offset pages.
    """
    try:
        printed_int = int(anchor.printed_page)
    except (ValueError, TypeError):
        return None

    start = printed_int
    end_exclusive = min(start + max_offset + 1, max(pages_text.keys(), default=0) + 1)

    # Pass A
    for pdf_page in range(start, end_exclusive):
        text = pages_text.get(pdf_page, "")
        if is_heading_like(text, anchor.title):
            return MatchResult(pdf_page=pdf_page, pass_="A")

    # Pass B
    for pdf_page in range(start, end_exclusive):
        text = pages_text.get(pdf_page, "")
        if fuzz.partial_ratio(anchor.title.lower(), text.lower()) >= fuzzy_threshold:
            return MatchResult(pdf_page=pdf_page, pass_="B")

    return None
