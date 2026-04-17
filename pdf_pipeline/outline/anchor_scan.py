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


@dataclass(frozen=True)
class OffsetResult:
    offset: int
    anchor: RawEntry
    match: MatchResult
    validated_count: int


def derive_offset(
    entries: list[RawEntry],
    pages_text: dict[int, str],
    max_offset: int = 100,
    min_validators: int = 2,
) -> OffsetResult | None:
    """Discover the printed→pdf_page offset by anchor scan + cross-validation.

    For each top-K candidate, try find_anchor_page; compute an offset;
    validate by checking whether 2+ other entries appear at their predicted
    pdf_page. Returns the first offset that passes validation, or None.
    """
    candidates = pick_anchor_candidates(entries, k=3)

    for anchor in candidates:
        match = find_anchor_page(anchor, pages_text, max_offset=max_offset)
        if match is None:
            continue
        try:
            anchor_printed = int(anchor.printed_page)
        except (ValueError, TypeError):
            continue
        offset = match.pdf_page - anchor_printed

        validators = [e for e in entries if e is not anchor]
        confirmed = 0
        for v in validators:
            try:
                predicted = int(v.printed_page) + offset
            except (ValueError, TypeError):
                continue
            text = pages_text.get(predicted, "")
            if fuzz.partial_ratio(v.title.lower(), text.lower()) >= _FUZZY_THRESHOLD_DEFAULT:
                confirmed += 1
                if confirmed >= min_validators:
                    break

        if confirmed >= min_validators:
            return OffsetResult(
                offset=offset,
                anchor=anchor,
                match=match,
                validated_count=confirmed,
            )

    return None


from pdf_pipeline.outline.schema import OutlineEntry


_CONFIDENCE_EXACT_A = 0.95
_CONFIDENCE_FUZZY_A = 0.85
_CONFIDENCE_B = 0.70
_CONFIDENCE_GLOBAL_ONLY = 0.50


def resolve_entries(
    entries: list[RawEntry],
    pages_text: dict[int, str],
    max_offset: int = 100,
) -> list[OutlineEntry]:
    """Turn raw TOC entries into OutlineEntry records with resolved pdf_pages.

    Discovers the offset once via anchor scan; applies it to all entries;
    cross-checks each entry individually and drops confidence if its own
    title doesn't appear at the predicted page.

    Entries whose pdf_page cannot be resolved at all are emitted with
    start_pdf_page = end_pdf_page = None, confidence = 0.0, source =
    "unresolved".
    """
    offset_result = derive_offset(entries, pages_text, max_offset=max_offset, min_validators=1)
    resolved: list[OutlineEntry] = []

    if offset_result is None:
        for i, raw in enumerate(entries):
            resolved.append(
                _to_unresolved(raw, idx=i)
            )
        return resolved

    offset = offset_result.offset

    for i, raw in enumerate(entries):
        try:
            printed_int = int(raw.printed_page)
        except (ValueError, TypeError):
            resolved.append(_to_unresolved(raw, idx=i))
            continue
        pdf_page = printed_int + offset
        text = pages_text.get(pdf_page, "")

        if raw is offset_result.anchor:
            if offset_result.match.pass_ == "A":
                confidence = _CONFIDENCE_EXACT_A
            else:
                confidence = _CONFIDENCE_B
        else:
            score = fuzz.partial_ratio(raw.title.lower(), text.lower())
            if score >= 95:
                confidence = _CONFIDENCE_EXACT_A
            elif score >= _FUZZY_THRESHOLD_DEFAULT:
                confidence = _CONFIDENCE_FUZZY_A
            else:
                confidence = _CONFIDENCE_GLOBAL_ONLY

        resolved.append(
            OutlineEntry(
                id=f"a{i}",
                title=raw.title,
                level=raw.level,
                parent_id=None,  # wired up later in orchestrator
                start_pdf_page=pdf_page,
                end_pdf_page=None,
                printed_page=raw.printed_page,
                confidence=confidence,
                source="anchor_scan",
            )
        )

    return resolved


def _to_unresolved(raw: RawEntry, idx: int) -> OutlineEntry:
    return OutlineEntry(
        id=f"u{idx}",
        title=raw.title,
        level=raw.level,
        parent_id=None,
        start_pdf_page=None,
        end_pdf_page=None,
        printed_page=raw.printed_page,
        confidence=0.0,
        source="unresolved",
    )
