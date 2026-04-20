from __future__ import annotations

import pytest

from essay_writer.research.schema import ResearchNote


def test_research_note_validates_confidence_and_page_range() -> None:
    with pytest.raises(ValueError, match="confidence"):
        ResearchNote(
            id="note",
            source_id="src",
            chunk_id="chunk",
            page_start=1,
            page_end=1,
            claim="Claim",
            quote=None,
            paraphrase="Paraphrase",
            relevance="Relevance",
            supports_topic=True,
            evidence_type="argument",
            confidence=1.5,
        )

    with pytest.raises(ValueError, match="page range"):
        ResearchNote(
            id="note",
            source_id="src",
            chunk_id="chunk",
            page_start=2,
            page_end=1,
            claim="Claim",
            quote=None,
            paraphrase="Paraphrase",
            relevance="Relevance",
            supports_topic=True,
            evidence_type="argument",
            confidence=0.5,
        )
