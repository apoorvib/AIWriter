from __future__ import annotations

import re

from essay_writer.drafting.anti_ai_rules import (
    BAD_CONCLUSION_OPENERS,
    SIGNPOSTING_PHRASES,
    TIER1_FLAGGED_VOCAB,
)
from essay_writer.validation.schema import (
    DeterministicCheckResult,
    ParagraphLengthProfile,
    SentenceRun,
    VocabHit,
)

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
_TRIPLET_RE = re.compile(
    r"\b[\w'-]+(?:\s+[\w'-]+)?\s*,\s*[\w'-]+(?:\s+[\w'-]+)?\s*,\s*(?:and|or)\s+[\w'-]+",
    re.IGNORECASE,
)
_CONCRETE_ENGAGEMENT_RE = re.compile(
    r"(\bpp?\.\s*\d+|\bpages?\s+\d+|\([A-Z][A-Za-z'-]+(?:\s+\d+|,\s*\d{4})\)|\"[^\"]{8,}\")"
)


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
    triplet_combo_count = _count_triplet_contrastive_combos(sentences)
    clustered_triplet_count = _count_clustered_triplets(sentences)
    paragraph_profile = _paragraph_length_profile(text)
    paragraph_variance_warning = (
        paragraph_profile is not None
        and paragraph_profile.paragraph_count >= 3
        and paragraph_profile.longest_to_shortest_ratio <= 1.3
    )
    mechanical_burstiness_count = _count_mechanical_burstiness(sentences)
    concrete_engagement_present = bool(_CONCRETE_ENGAGEMENT_RE.search(text))

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
        triplet_contrastive_combo_count=triplet_combo_count,
        clustered_triplet_count=clustered_triplet_count,
        paragraph_length_profile=paragraph_profile,
        paragraph_length_variance_warning=paragraph_variance_warning,
        mechanical_burstiness_count=mechanical_burstiness_count,
        concrete_engagement_present=concrete_engagement_present,
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


def _count_triplet_contrastive_combos(sentences: list[str]) -> int:
    count = 0
    lowered = [sentence.lower() for sentence in sentences]
    for idx, sentence in enumerate(lowered):
        if not any(re.search(pattern, sentence) for pattern in _CONTRASTIVE_NEGATION_PATTERNS):
            continue
        window = " ".join(lowered[max(0, idx - 2) : idx + 3])
        if _TRIPLET_RE.search(window):
            count += 1
    return count


def _count_clustered_triplets(sentences: list[str]) -> int:
    triplet_positions = [
        idx for idx, sentence in enumerate(sentences) if _TRIPLET_RE.search(sentence)
    ]
    if len(triplet_positions) < 2:
        return 0
    clusters = 0
    for idx, position in enumerate(triplet_positions[:-1]):
        if triplet_positions[idx + 1] - position <= 3:
            clusters += 1
    return clusters


def _paragraph_length_profile(text: str) -> ParagraphLengthProfile | None:
    counts = [
        len(paragraph.split())
        for paragraph in text.strip().split("\n\n")
        if paragraph.strip()
    ]
    if not counts:
        return None
    shortest = min(counts)
    longest = max(counts)
    ratio = (longest / shortest) if shortest else float("inf")
    return ParagraphLengthProfile(
        paragraph_count=len(counts),
        shortest_word_count=shortest,
        longest_word_count=longest,
        longest_to_shortest_ratio=ratio,
    )


def _count_mechanical_burstiness(sentences: list[str]) -> int:
    counts = [len(sentence.split()) for sentence in sentences]
    total = 0
    for idx in range(1, len(counts) - 1):
        if counts[idx] < 8 and counts[idx - 1] >= 12 and counts[idx + 1] >= 12:
            total += 1
    return total
