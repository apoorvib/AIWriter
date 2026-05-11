from __future__ import annotations

import re

from essay_writer.sources.schema import SourcePage


_COMMON_WORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "of", "in", "to", "is", "are",
        "was", "were", "be", "been", "for", "with", "as", "on", "at", "by",
        "this", "that", "these", "those", "it", "its", "from", "not", "no",
        "we", "you", "they", "their", "our", "his", "her", "have", "has",
        "had", "do", "does", "did", "can", "could", "should", "would", "will",
        "may", "must", "if", "then", "than", "so", "such", "which", "who",
        "what", "when", "where", "why", "how", "all", "any", "some", "more",
        "most", "less", "many", "much", "one", "two", "first", "also", "only",
        "very", "out", "up", "into", "between", "about", "after", "before",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z]+")


def text_signal_score(text: str) -> float:
    """Return a 0–1 score indicating how prose-like the text is. Used to
    decide whether a longer OCR result is actually higher-signal than a
    shorter text-layer extraction, instead of relying on raw character
    count (which OCR pollution can game)."""
    if not text or not text.strip():
        return 0.0
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return 0.0
    word_like = sum(1 for token in tokens if _looks_like_word(token))
    common_hits = sum(1 for token in tokens if token.lower() in _COMMON_WORDS)
    word_rate = word_like / len(tokens)
    common_target = max(len(tokens) * 0.05, 1.0)
    common_boost = min(common_hits / common_target, 1.0)
    cleanish = sum(
        1 for ch in text if ch.isalpha() or ch.isspace() or ch in ",.;:!?-'\"()"
    )
    composition_rate = cleanish / len(text)
    return 0.5 * word_rate + 0.3 * common_boost + 0.2 * composition_rate


def is_better_extraction(candidate: SourcePage, current: SourcePage | None) -> bool:
    """Decide whether `candidate` should replace `current` when both extractions
    target the same page. Conservative: a longer-but-noisier OCR result will
    not displace a shorter cleaner text-layer extraction.

    Replacement rule:
    1. Empty candidate never wins.
    2. Missing/empty current always loses to non-empty candidate.
    3. Candidate's signal score must be >= current's score (strict gate).
    4. Among comparable scores, candidate wins iff it adds length OR
       has strictly higher score.
    """
    if not candidate.text or not candidate.text.strip():
        return False
    if current is None or not current.text or not current.text.strip():
        return True
    cand_score = text_signal_score(candidate.text)
    curr_score = text_signal_score(current.text)
    if cand_score < curr_score:
        return False
    if cand_score > curr_score:
        return True
    return candidate.char_count > current.char_count


def _looks_like_word(token: str) -> bool:
    if not (2 <= len(token) <= 18):
        return False
    if not token.isalpha():
        return False
    return any(ch in "aeiouAEIOU" for ch in token)
