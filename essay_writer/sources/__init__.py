"""Source document ingestion and indexing."""

from essay_writer.sources.ingestion import (
    FileTooLargeWithoutIndexError,
    SourceIngestionError,
    SourceIngestionService,
)
from essay_writer.sources.index import ChunkSearchResult, SQLiteChunkIndex
from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.schema import (
    SourceCard,
    SourceChunk,
    SourceDocument,
    SourceIndexEntry,
    SourceIndexManifest,
    SourceIngestionConfig,
    SourceIngestionResult,
    SourcePage,
)
from essay_writer.sources.storage import SourceStore

__all__ = [
    "ChunkSearchResult",
    "FileTooLargeWithoutIndexError",
    "SQLiteChunkIndex",
    "SourceCard",
    "SourceChunk",
    "SourceDocument",
    "SourceIndexEntry",
    "SourceIndexManifest",
    "SourceIngestionConfig",
    "SourceIngestionError",
    "SourceIngestionResult",
    "SourceIngestionService",
    "SourcePage",
    "SourceStore",
    "build_index_manifest",
]
