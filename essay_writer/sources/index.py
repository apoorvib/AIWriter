from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from essay_writer.sources.schema import SourceChunk


class SourceIndexError(RuntimeError):
    """Raised when the local source index cannot be created or queried."""


@dataclass(frozen=True)
class ChunkSearchResult:
    chunk_id: str
    source_id: str
    page_start: int
    page_end: int
    text: str
    score: float


class SQLiteChunkIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteChunkIndex:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def reset(self) -> None:
        self._conn.execute("DELETE FROM chunk_fts")
        self._conn.commit()

    def add_chunks(self, chunks: list[SourceChunk]) -> None:
        self._conn.executemany(
            """
            INSERT INTO chunk_fts(chunk_id, source_id, ordinal, page_start, page_end, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.id,
                    chunk.source_id,
                    chunk.ordinal,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.text,
                )
                for chunk in chunks
            ],
        )
        self._conn.commit()

    def search(self, query: str, *, limit: int = 5) -> list[ChunkSearchResult]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        match_query = _match_query(query)
        if not match_query:
            return []
        try:
            rows = self._conn.execute(
                """
                SELECT chunk_id, source_id, page_start, page_end, text, bm25(chunk_fts) AS rank
                FROM chunk_fts
                WHERE chunk_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SourceIndexError(f"source index query failed: {exc}") from exc
        return [
            ChunkSearchResult(
                chunk_id=str(row["chunk_id"]),
                source_id=str(row["source_id"]),
                page_start=int(row["page_start"]),
                page_end=int(row["page_end"]),
                text=str(row["text"]),
                score=float(row["rank"]),
            )
            for row in rows
        ]

    def _ensure_schema(self) -> None:
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    chunk_id UNINDEXED,
                    source_id UNINDEXED,
                    ordinal UNINDEXED,
                    page_start UNINDEXED,
                    page_end UNINDEXED,
                    text
                )
                """
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise SourceIndexError(f"could not initialize source index: {exc}") from exc


def _match_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_]+", query.lower())
    if not terms:
        return ""
    return " OR ".join(dict.fromkeys(terms))
