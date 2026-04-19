from __future__ import annotations

from essay_writer.sources.index import SQLiteChunkIndex
from essay_writer.sources.schema import SourceChunk
from tests.task_spec._tmp import LocalTempDir


def test_sqlite_chunk_index_searches_real_chunks() -> None:
    chunks = [
        SourceChunk(
            id="c1",
            source_id="src1",
            ordinal=1,
            page_start=1,
            page_end=1,
            text="Climate policy depends on energy infrastructure and public trust.",
            char_count=67,
        ),
        SourceChunk(
            id="c2",
            source_id="src1",
            ordinal=2,
            page_start=2,
            page_end=2,
            text="Medieval trade networks expanded through port cities.",
            char_count=55,
        ),
    ]
    with LocalTempDir() as tmp_path:
        index_path = tmp_path / "index.sqlite"
        with SQLiteChunkIndex(index_path) as index:
            index.add_chunks(chunks)
            results = index.search("climate energy", limit=3)

    assert [result.chunk_id for result in results] == ["c1"]
    assert results[0].page_start == 1
    assert "energy infrastructure" in results[0].text
