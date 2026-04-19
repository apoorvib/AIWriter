"""Cheap heuristic to detect whether a page looks like part of a TOC."""
from __future__ import annotations

import re
from typing import Mapping

_HEADING_PATTERN = re.compile(
    r"^\s*(table of contents|contents)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DOT_LEADER_PATTERN = re.compile(r"\.{3,}\s*\d+\s*$", re.MULTILINE)
_SHORT_LINE_NUM_PATTERN = re.compile(r"^\s*\S.{0,60}?\s+\d+\s*$", re.MULTILINE)
_PAGE_HEADING_PATTERN = re.compile(r"^\s*page\.?\s+(page\.?)?\s*$", re.IGNORECASE | re.MULTILINE)


def looks_like_toc(text: str) -> bool:
    """Heuristically decide whether `text` looks like TOC content.

    Triggers on any of: a "Contents"/"Table of Contents" heading, three or
    more dot-leader lines, or ten or more short lines that end in a number.
    """
    if not text or not text.strip():
        return False

    if _HEADING_PATTERN.search(text):
        return True

    if len(_DOT_LEADER_PATTERN.findall(text)) >= 3:
        return True

    if len(_SHORT_LINE_NUM_PATTERN.findall(text)) >= 10:
        return True

    return False


def toc_page_score(text: str) -> int:
    """Return a cheap TOC-likeness score for one page of extracted text."""
    if not text or not text.strip():
        return 0

    score = 0
    if _HEADING_PATTERN.search(text):
        score += 8
    if _PAGE_HEADING_PATTERN.search(text):
        score += 2
    score += min(len(_DOT_LEADER_PATTERN.findall(text)), 8)
    score += min(len(_SHORT_LINE_NUM_PATTERN.findall(text)) // 2, 8)
    return score


def select_toc_candidate_pages(
    pages_text: Mapping[int, str],
    *,
    min_score: int = 3,
    max_gap: int = 1,
    padding: int = 1,
    max_pages: int = 24,
) -> list[int]:
    """Pick the most likely contiguous TOC window before LLM extraction.

    The outline pipeline scans a broad front-matter window because books vary
    widely. Calling the LLM over every chunk in that window is expensive and
    brittle. This selector keeps the highest-scoring contiguous TOC-looking
    run, expands it slightly for boundary pages, and caps the result.
    """
    if not pages_text:
        return []

    scored = {page: toc_page_score(text) for page, text in pages_text.items()}
    candidates = sorted(page for page, score in scored.items() if score >= min_score)
    if not candidates:
        return []

    groups: list[list[int]] = []
    current = [candidates[0]]
    for page in candidates[1:]:
        if page - current[-1] <= max_gap + 1:
            current.append(page)
        else:
            groups.append(current)
            current = [page]
    groups.append(current)

    def group_key(group: list[int]) -> tuple[int, int, int]:
        return (sum(scored[p] for p in group), len(group), -group[0])

    best = max(groups, key=group_key)
    all_pages = sorted(pages_text)
    min_available = all_pages[0]
    max_available = all_pages[-1]
    start = max(min_available, best[0] - padding)
    end = min(max_available, best[-1] + padding)
    selected = [p for p in range(start, end + 1) if p in pages_text]

    if len(selected) > max_pages:
        selected = _trim_to_scored_center(selected, scored, max_pages)
    return selected


def _trim_to_scored_center(pages: list[int], scored: dict[int, int], max_pages: int) -> list[int]:
    best_page = max(pages, key=lambda page: (scored.get(page, 0), -page))
    half = max_pages // 2
    start = best_page - half
    end = start + max_pages - 1
    if start < pages[0]:
        start = pages[0]
        end = start + max_pages - 1
    if end > pages[-1]:
        end = pages[-1]
        start = end - max_pages + 1
    return [p for p in pages if start <= p <= end]
