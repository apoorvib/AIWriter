from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from llm.client import LLMClient
from pdf_pipeline.document_reader import DocumentReader
from pdf_pipeline.models import DocumentExtractionResult
from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig
from pdf_pipeline.pipeline import ExtractionPipeline
from essay_writer.sources.chunking import chunk_pages
from essay_writer.sources.index import SQLiteChunkIndex, SourceIndexError
from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.schema import (
    SourceDocument,
    SourceIndexManifest,
    SourceIngestionConfig,
    SourceIngestionResult,
    SourcePage,
)
from essay_writer.sources.storage import SourceStore
from essay_writer.sources.summary import build_source_card


class SourceIngestionError(RuntimeError):
    """Base error for source ingestion failures."""


class FileTooLargeWithoutIndexError(SourceIngestionError):
    """Raised when a source exceeds direct-read limits and cannot be indexed."""


class Extractor(Protocol):
    def extract(self, document_path: str | Path) -> DocumentExtractionResult: ...


class SourceIngestionService:
    def __init__(
        self,
        store: SourceStore,
        *,
        config: SourceIngestionConfig | None = None,
        document_reader: Extractor | None = None,
        ocr_extractor: Extractor | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._store = store
        self._config = config or SourceIngestionConfig()
        self._document_reader = document_reader or DocumentReader()
        self._ocr_extractor = ocr_extractor
        self._llm_client = llm_client

    def ingest(self, document_path: str | Path, *, source_id: str | None = None) -> SourceIngestionResult:
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"source document not found: {path}")
        resolved_id = source_id or _source_id(path)
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
        source_card = build_source_card(
            source,
            chunks,
            llm_client=self._llm_client,
            input_char_budget=self._config.source_card_input_char_budget,
            summary_char_limit=self._config.source_card_summary_char_limit,
        )
        result = SourceIngestionResult(
            source=source,
            pages=pages,
            chunks=chunks,
            source_card=source_card,
            indexed=indexed,
            full_text_available=full_text_available,
            index_manifest=index_manifest,
            warnings=warnings,
        )
        return self._store.save_result(result)

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


def _source_pages(source_id: str, result: DocumentExtractionResult) -> list[SourcePage]:
    return [
        SourcePage(
            source_id=source_id,
            page_number=page.page_number,
            text=page.text,
            char_count=page.char_count,
            extraction_method=page.extraction_method,
        )
        for page in result.pages
    ]


def _merge_partial_ocr_pages(
    text_pages: list[SourcePage],
    ocr_pages: list[SourcePage],
    config: SourceIngestionConfig,
) -> list[SourcePage]:
    ocr_by_page = {page.page_number: page for page in ocr_pages}
    merged: list[SourcePage] = []
    seen: set[int] = set()
    for page in text_pages:
        seen.add(page.page_number)
        ocr_page = ocr_by_page.get(page.page_number)
        if (
            page.char_count < config.min_text_chars_per_page
            and ocr_page is not None
            and ocr_page.char_count > page.char_count
        ):
            merged.append(ocr_page)
        else:
            merged.append(page)
    for page in ocr_pages:
        if page.page_number not in seen:
            merged.append(page)
    return sorted(merged, key=lambda item: item.page_number)


def _text_quality(pages: list[SourcePage], config: SourceIngestionConfig) -> str:
    if not pages:
        return "low"
    readable_pages = sum(1 for page in pages if page.char_count >= config.min_text_chars_per_page)
    readable_ratio = readable_pages / len(pages)
    if readable_ratio >= config.min_readable_page_ratio:
        return "readable"
    if any(page.char_count > 0 for page in pages):
        return "partial"
    return "low"


def _extraction_method(pages: list[SourcePage]) -> str:
    methods = sorted({page.extraction_method for page in pages})
    if not methods:
        return "unknown"
    if len(methods) == 1:
        return methods[0]
    return "+".join(methods)


def _within_full_read_budget(page_count: int, char_count: int, config: SourceIngestionConfig) -> bool:
    return page_count <= config.max_full_read_pages and char_count <= config.max_full_read_chars


def _requires_index(page_count: int, char_count: int, config: SourceIngestionConfig) -> bool:
    return page_count > config.max_indexless_pages or char_count > config.max_indexless_chars


def _too_large_without_index_message(
    page_count: int,
    char_count: int,
    config: SourceIngestionConfig,
) -> str:
    return (
        "source has "
        f"{page_count} pages and {char_count} characters, exceeds "
        f"max_indexless_pages={config.max_indexless_pages} or "
        f"max_indexless_chars={config.max_indexless_chars}, and no index is available"
    )


def _source_id(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"src-{digest.hexdigest()[:16]}"
