"""Layer 3: deterministic offset resolution via anchor scan."""
from __future__ import annotations

import re
from dataclasses import dataclass

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
