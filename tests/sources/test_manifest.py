from __future__ import annotations

from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.schema import SourceChunk


def test_index_manifest_contains_complete_chunk_map_for_ideation() -> None:
    chunks = [
        SourceChunk(
            id="src1-chunk-0001",
            source_id="src1",
            ordinal=1,
            page_start=1,
            page_end=2,
            text="INTRODUCTION\nThis section frames climate adaptation and housing policy.",
            char_count=68,
        ),
        SourceChunk(
            id="src1-chunk-0002",
            source_id="src1",
            ordinal=2,
            page_start=3,
            page_end=5,
            text="Evidence on urban heat islands, zoning, and public health.",
            char_count=59,
        ),
    ]

    manifest = build_index_manifest(source_id="src1", index_path="index.sqlite", chunks=chunks)
    context = manifest.to_context(max_preview_chars=120)

    assert manifest.total_chunks == 2
    assert [entry.chunk_id for entry in manifest.entries] == ["src1-chunk-0001", "src1-chunk-0002"]
    assert "INTRODUCTION" in manifest.entries[0].heading
    assert "src1-chunk-0001" in context
    assert "src1-chunk-0002" in context
