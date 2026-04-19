from __future__ import annotations

from essay_writer.sources.chunking import chunk_pages
from essay_writer.sources.schema import SourcePage


def test_chunk_pages_preserves_page_ranges() -> None:
    pages = [
        SourcePage(
            source_id="src1",
            page_number=1,
            text="alpha " * 120,
            char_count=len("alpha " * 120),
            extraction_method="pypdf",
        ),
        SourcePage(
            source_id="src1",
            page_number=2,
            text="beta " * 120,
            char_count=len("beta " * 120),
            extraction_method="pypdf",
        ),
    ]

    chunks = chunk_pages(pages, source_id="src1", target_chars=400, overlap_chars=50)

    assert chunks
    assert chunks[0].source_id == "src1"
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2
    assert all(chunk.char_count == len(chunk.text) for chunk in chunks)
