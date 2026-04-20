"""Source document ingestion and indexing."""

from essay_writer.sources.ingestion import (
    FileTooLargeWithoutIndexError,
    SourceIngestionError,
    SourceIngestionService,
)
from essay_writer.sources.index import ChunkSearchResult, SQLiteChunkIndex
from essay_writer.sources.lazy_ocr import DefaultPdfPageOcrProvider, PdfPageOcrProvider
from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.access_schema import (
    SourceAccessConfig,
    SourceLocator,
    SourceMap,
    SourceTextPacket,
    SourceUnit,
)
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
    "DefaultPdfPageOcrProvider",
    "PdfPageOcrProvider",
    "SQLiteChunkIndex",
    "SourceCard",
    "SourceAccessConfig",
    "SourceChunk",
    "SourceDocument",
    "SourceIndexEntry",
    "SourceIndexManifest",
    "SourceIngestionConfig",
    "SourceIngestionError",
    "SourceIngestionResult",
    "SourceIngestionService",
    "SourceLocator",
    "SourceMap",
    "SourcePage",
    "SourceStore",
    "SourceTextPacket",
    "SourceUnit",
    "build_index_manifest",
]
