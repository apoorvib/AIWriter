from __future__ import annotations

from pathlib import Path

from pdf_pipeline.document_reader import DocumentReader
from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig
from pdf_pipeline.pipeline import ExtractionPipeline

from essay_writer.sources.chunking import chunk_pages
from essay_writer.sources.index import SQLiteChunkIndex, SourceIndexError
from essay_writer.sources.ingestion import (
    Extractor,
    FileTooLargeWithoutIndexError,
    _extraction_method,
    _merge_partial_ocr_pages,
    _read_pdf_page_labels,
    _requires_index,
    _source_id,
    _source_pages,
    _text_quality,
    _too_large_without_index_message,
    _within_full_read_budget,
)
from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.map import build_source_map
from essay_writer.sources.schema import (
    SourceDocument,
    SourceIndexManifest,
    SourceIngestionConfig,
    SourceMaterializationResult,
    SourcePage,
)
from essay_writer.sources.storage import SourceStore


class SourceMaterializationService:
    def __init__(
        self,
        store: SourceStore,
        *,
        config: SourceIngestionConfig | None = None,
        document_reader: Extractor | None = None,
        ocr_extractor: Extractor | None = None,
    ) -> None:
        self._store = store
        self._config = config or SourceIngestionConfig()
        self._document_reader = document_reader or DocumentReader()
        self._ocr_extractor = ocr_extractor

    def materialize(
        self,
        document_path: str | Path,
        *,
        source_id: str | None = None,
    ) -> SourceMaterializationResult:
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"source document not found: {path}")
        resolved_id = source_id or _source_id(path)

        if self._store.has_text_artifacts(resolved_id):
            return self._store.load_materialized_source(resolved_id)

        warnings: list[str] = []

        text_result = self._document_reader.extract(path)
        text_pages = _source_pages(resolved_id, text_result)
        text_quality = _text_quality(text_pages, self._config)
        extraction_method = _extraction_method(text_pages)

        pages = text_pages
        if path.suffix.lower() == ".pdf" and text_quality in {"low", "partial"}:
            ocr_pages = self._extract_ocr_pages(path, resolved_id)
            if text_quality == "partial":
                pages = _merge_partial_ocr_pages(text_pages, ocr_pages, self._config)
            else:
                pages = ocr_pages
            text_quality = _text_quality(pages, self._config)
            extraction_method = _extraction_method(pages)
            if text_quality == "low":
                warnings.append("OCR completed, but extracted text quality is still low.")

        char_count = sum(page.char_count for page in pages)
        page_count = text_result.page_count if text_result.page_count else len(pages)
        full_text_available = _within_full_read_budget(page_count, char_count, self._config)
        large_without_index = _requires_index(page_count, char_count, self._config)
        chunks = chunk_pages(
            pages,
            source_id=resolved_id,
            target_chars=self._config.chunk_target_chars,
            overlap_chars=self._config.chunk_overlap_chars,
        )
        if not chunks and char_count == 0:
            warnings.append("No readable text was extracted from the source.")

        indexed = False
        index_manifest: SourceIndexManifest | None = None
        index_path = self._store.source_dir(resolved_id) / "index.sqlite"
        if self._config.index_sources and chunks:
            try:
                with SQLiteChunkIndex(index_path) as index:
                    index.reset()
                    index.add_chunks(chunks)
                indexed = True
                index_manifest = build_index_manifest(
                    source_id=resolved_id,
                    index_path=str(index_path),
                    chunks=chunks,
                )
            except SourceIndexError as exc:
                if large_without_index and self._config.require_index_for_large_sources:
                    raise FileTooLargeWithoutIndexError(
                        _too_large_without_index_message(page_count, char_count, self._config)
                    ) from exc
                warnings.append("Source index could not be created.")

        if large_without_index and not indexed and self._config.require_index_for_large_sources:
            raise FileTooLargeWithoutIndexError(
                _too_large_without_index_message(page_count, char_count, self._config)
            )

        source = SourceDocument(
            id=resolved_id,
            original_path=str(path),
            file_name=path.name,
            source_type=path.suffix.lower().lstrip(".") or "unknown",
            page_count=page_count,
            char_count=char_count,
            extraction_method=extraction_method,
            text_quality=text_quality,
            full_text_available=full_text_available,
            indexed=indexed,
            index_path=str(index_path) if indexed else None,
        )
        printed_page_labels = _read_pdf_page_labels(path) if path.suffix.lower() == ".pdf" else None
        source_map = build_source_map(source, pages, printed_page_labels=printed_page_labels)
        result = SourceMaterializationResult(
            source=source,
            pages=pages,
            chunks=chunks,
            indexed=indexed,
            full_text_available=full_text_available,
            index_manifest=index_manifest,
            source_map=source_map,
            warnings=warnings,
        )
        return self._store.save_materialized_source(result)

    def _extract_ocr_pages(self, path: Path, source_id: str) -> list[SourcePage]:
        extractor = self._ocr_extractor
        if extractor is None:
            extractor = ExtractionPipeline(
                mode=ExtractionMode.OCR_ONLY,
                ocr_tier=self._config.ocr_tier,
                ocr_config=OcrConfig(),
            )
        ocr_result = extractor.extract(path)
        return _source_pages(source_id, ocr_result)
