from __future__ import annotations

from pathlib import Path

import pytest

from essay_writer.sources import FileTooLargeWithoutIndexError, SourceIngestionService, SourceStore
from essay_writer.sources.schema import SourceIngestionConfig
from pdf_pipeline.models import DocumentExtractionResult, PageText
from tests.task_spec._tmp import LocalTempDir


class FakeExtractor:
    def __init__(self, result: DocumentExtractionResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def extract(self, document_path: str | Path) -> DocumentExtractionResult:
        self.calls.append(Path(document_path))
        return self.result


def test_ingests_short_pdf_with_full_text_artifacts_and_index() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "short.pdf")
        reader = FakeExtractor(_result(source_path, page_count=2, page_texts=["Climate justice overview.", "Use cases for policy essays."]))
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(min_text_chars_per_page=5, source_card_context_char_budget=1_000),
            document_reader=reader,
        )

        result = service.ingest(source_path, source_id="src-short")
        source_dir = tmp_path / "source_store" / "src-short"
        assert (source_dir / "source.json").exists()
        assert (source_dir / "pages.jsonl").exists()
        assert (source_dir / "chunks.jsonl").exists()
        assert (source_dir / "index.sqlite").exists()
        assert (source_dir / "index_manifest.json").exists()

    assert result.source.page_count == 2
    assert result.full_text_available is True
    assert result.indexed is True
    assert result.source.index_manifest_path is not None
    assert result.index_manifest is not None
    assert result.index_manifest.total_chunks == len(result.chunks)
    assert len(result.source_card.to_context(max_chars=500)) <= 500


def test_long_readable_pdf_is_chunked_and_indexed_not_full_read() -> None:
    page_texts = [f"Page {idx} climate adaptation infrastructure resilience." for idx in range(1, 8)]
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "long.pdf")
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(
                max_full_read_pages=3,
                max_indexless_pages=3,
                min_text_chars_per_page=10,
                chunk_target_chars=250,
                chunk_overlap_chars=25,
            ),
            document_reader=FakeExtractor(_result(source_path, page_count=7, page_texts=page_texts)),
        )

        result = service.ingest(source_path, source_id="src-long")

    assert result.full_text_available is False
    assert result.indexed is True
    assert len(result.chunks) >= 2
    assert result.source.index_path is not None
    assert result.source.index_manifest_path is not None
    assert result.index_manifest is not None
    assert len(result.index_manifest.entries) == len(result.chunks)


def test_long_source_without_index_raises() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "no_index.pdf")
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(
                index_sources=False,
                max_full_read_pages=3,
                max_indexless_pages=3,
                min_text_chars_per_page=10,
            ),
            document_reader=FakeExtractor(
                _result(
                    source_path,
                    page_count=5,
                    page_texts=[f"Readable policy source page {idx}." for idx in range(1, 6)],
                )
            ),
        )

        with pytest.raises(FileTooLargeWithoutIndexError):
            service.ingest(source_path, source_id="src-no-index")


def test_low_text_pdf_routes_to_ocr_then_indexes() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "scanned.pdf")
        reader = FakeExtractor(_result(source_path, page_count=2, page_texts=["", ""]))
        ocr = FakeExtractor(_result(source_path, page_count=2, page_texts=["OCR policy evidence.", "OCR conclusion."], method="tesseract"))
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=reader,
            ocr_extractor=ocr,
        )

        result = service.ingest(source_path, source_id="src-ocr")

    assert reader.calls == [source_path]
    assert ocr.calls == [source_path]
    assert result.source.extraction_method == "tesseract"
    assert result.indexed is True
    assert result.pages[0].text == "OCR policy evidence."


def test_partial_pdf_uses_ocr_for_unreadable_pages_only() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "mixed.pdf")
        reader = FakeExtractor(_result(source_path, page_count=2, page_texts=["Readable embedded text page.", ""]))
        ocr = FakeExtractor(
            _result(
                source_path,
                page_count=2,
                page_texts=["Noisy OCR duplicate.", "OCR recovered scanned page."],
                method="tesseract",
            )
        )
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=reader,
            ocr_extractor=ocr,
        )

        result = service.ingest(source_path, source_id="src-mixed")

    assert reader.calls == [source_path]
    assert ocr.calls == [source_path]
    assert result.pages[0].text == "Readable embedded text page."
    assert result.pages[0].extraction_method == "pypdf"
    assert result.pages[1].text == "OCR recovered scanned page."
    assert result.pages[1].extraction_method == "tesseract"
    assert result.source.extraction_method == "pypdf+tesseract"
    assert result.indexed is True


def test_unreadable_short_source_is_not_marked_indexed_when_no_chunks_exist() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "empty.pdf")
        reader = FakeExtractor(_result(source_path, page_count=1, page_texts=[""]))
        ocr = FakeExtractor(_result(source_path, page_count=1, page_texts=[""], method="tesseract"))
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=reader,
            ocr_extractor=ocr,
        )

        result = service.ingest(source_path, source_id="src-empty")
        source_dir = tmp_path / "source_store" / "src-empty"

    assert result.chunks == []
    assert result.indexed is False
    assert result.index_manifest is None
    assert result.source.index_path is None
    assert not (source_dir / "index_manifest.json").exists()
    assert any("No readable text" in warning for warning in result.warnings)


def test_long_unreadable_source_with_no_chunks_raises_even_when_indexing_enabled() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "long_empty.pdf")
        reader = FakeExtractor(_result(source_path, page_count=5, page_texts=["", "", "", "", ""]))
        ocr = FakeExtractor(_result(source_path, page_count=5, page_texts=["", "", "", "", ""], method="tesseract"))
        service = SourceIngestionService(
            SourceStore(tmp_path / "source_store"),
            config=SourceIngestionConfig(
                max_indexless_pages=3,
                min_text_chars_per_page=5,
            ),
            document_reader=reader,
            ocr_extractor=ocr,
        )

        with pytest.raises(FileTooLargeWithoutIndexError, match="no index is available"):
            service.ingest(source_path, source_id="src-long-empty")


def _touch_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-pretend-for-fake-extractor")
    return path


def _result(
    source_path: Path,
    *,
    page_count: int,
    page_texts: list[str],
    method: str = "pypdf",
) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        source_path=str(source_path),
        page_count=page_count,
        pages=[
            PageText(
                page_number=idx,
                text=text,
                char_count=len(text),
                extraction_method=method,
            )
            for idx, text in enumerate(page_texts, start=1)
        ],
    )
