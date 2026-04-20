from __future__ import annotations

import re
from pathlib import Path

from essay_writer.sources.schema import SourceCard
from essay_writer.validation.schema import CitationMetadataWarning


def check_bibliography_against_source_cards(
    bibliography_candidates: list[str],
    source_cards: list[SourceCard],
) -> list[CitationMetadataWarning]:
    """Check draft bibliography candidates against metadata known at ingestion time."""
    if not source_cards:
        return []

    candidates = [candidate.strip() for candidate in bibliography_candidates if candidate.strip()]
    if not candidates:
        return [
            CitationMetadataWarning(
                source_id=card.source_id,
                description="No bibliography candidate references this uploaded source.",
                severity="medium",
            )
            for card in source_cards
        ]

    candidate_text = _normalize(" ".join(candidates))
    warnings: list[CitationMetadataWarning] = []
    for card in source_cards:
        identifiers = _metadata_identifiers(card)
        if identifiers and any(identifier in candidate_text for identifier in identifiers):
            continue
        warnings.append(
            CitationMetadataWarning(
                source_id=card.source_id,
                description="Bibliography candidates do not appear to reference this source's known title or citation metadata.",
                severity="medium",
            )
        )
    return warnings


def source_metadata_context(source_cards: list[SourceCard]) -> list[dict[str, object]]:
    return [
        {
            "source_id": card.source_id,
            "title": card.title,
            "source_type": card.source_type,
            "page_count": card.page_count,
            "citation_metadata": card.citation_metadata,
        }
        for card in source_cards
    ]


def _metadata_identifiers(card: SourceCard) -> list[str]:
    raw_values = [card.title, *card.citation_metadata.values()]
    file_name = card.citation_metadata.get("file_name")
    if file_name:
        raw_values.append(Path(file_name).stem)

    identifiers: list[str] = []
    for value in raw_values:
        normalized = _normalize(value)
        if len(normalized) < 3:
            continue
        identifiers.append(normalized)
        if " " in normalized:
            significant_terms = [term for term in normalized.split() if len(term) >= 4]
            if len(significant_terms) >= 2:
                identifiers.append(" ".join(significant_terms[:4]))
    return _dedupe(identifiers)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
