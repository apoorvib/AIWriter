from __future__ import annotations

import re

from essay_writer.drafting.anti_ai_rules import (
    BAD_CONCLUSION_OPENERS,
    SIGNPOSTING_PHRASES,
    TIER1_FLAGGED_VOCAB,
)
from essay_writer.validation.schema import DeterministicCheckResult, SentenceRun, VocabHit

_CONTRASTIVE_NEGATION_PATTERNS: list[str] = [
    r"\bnot just\b",
    r"\bnot only\b",
    r"\bit'?s not\b",
    r"\bisn'?t about\b",
    r"\bit is not\b",
    r"\bit goes beyond\b",
    r"\bmore than just\b",
]

_PARTICIPIAL_RE = re.compile(r",\s+\w+ing\b", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def run_deterministic_checks(text: str) -> DeterministicCheckResult:
    lower = text.lower()
    word_count = len(text.split())

    em_dash_count = text.count("\u2014")

    tier1_hits = _check_tier1_vocab(lower)

    bad_conclusion_opener = _check_conclusion_opener(text)

    sentences = _split_sentences(text)
    similar_runs = _find_similar_length_runs(sentences)

    participial_matches = _PARTICIPIAL_RE.findall(text)
    participial_count = len(participial_matches)
    participial_rate = (participial_count / word_count * 300) if word_count > 0 else 0.0

    contrastive_count = sum(
        len(re.findall(p, lower)) for p in _CONTRASTIVE_NEGATION_PATTERNS
    )

    signposting_hits = [p for p in SIGNPOSTING_PHRASES if p in lower]

    return DeterministicCheckResult(
        word_count=word_count,
        em_dash_count=em_dash_count,
        tier1_vocab_hits=tier1_hits,
        bad_conclusion_opener=bad_conclusion_opener,
        consecutive_similar_sentence_runs=similar_runs,
        participial_phrase_count=participial_count,
        participial_phrase_rate=participial_rate,
        contrastive_negation_count=contrastive_count,
        signposting_hits=signposting_hits,
    )


def _check_tier1_vocab(lower_text: str) -> list[VocabHit]:
    hits = []
    for word in TIER1_FLAGGED_VOCAB:
        count = len(re.findall(r"\b" + re.escape(word) + r"\b", lower_text))
        if count > 0:
            hits.append(VocabHit(word=word, count=count))
    return hits


def _check_conclusion_opener(text: str) -> bool:
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    if not paragraphs:
        return False
    last = paragraphs[-1].lower()
    return any(last.startswith(opener) for opener in BAD_CONCLUSION_OPENERS)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _find_similar_length_runs(
    sentences: list[str],
    min_run: int = 3,
    similarity_threshold: float = 0.35,
) -> list[SentenceRun]:
    if len(sentences) < min_run:
        return []

    counts = [len(s.split()) for s in sentences]
    runs: list[SentenceRun] = []
    i = 0

    while i <= len(counts) - min_run:
        j = i + 1
        while j < len(counts):
            window = counts[i : j + 1]
            avg = sum(window) / len(window)
            if avg == 0 or (max(window) - min(window)) / avg <= similarity_threshold:
                j += 1
            else:
                break
        run_len = j - i
        if run_len >= min_run:
            window = counts[i:j]
            avg = sum(window) / len(window)
            runs.append(SentenceRun(sentence_count=run_len, avg_word_count=avg))
            i = j
        else:
            i += 1

    return runs
