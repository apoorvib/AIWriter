from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from essay_writer.sources.access import SourceAccessService
from essay_writer.sources.access_schema import SourceAccessConfig, SourceLocator
from essay_writer.sources.map import build_source_map
from essay_writer.sources.schema import SourceChunk, SourceDocument, SourceIngestionResult, SourcePage, SourceCard
from essay_writer.sources.storage import SourceStore


def test_markdown_source_map_uses_heading_sections() -> None:
    source = _source("src-md", source_type="md")
    pages = [
        SourcePage(
            source_id="src-md",
            page_number=1,
            text="# Intro\nOpening text.\n\n## Evidence\nDetailed evidence here.",
            char_count=55,
            extraction_method="plain_text",
        )
    ]

    source_map = build_source_map(source, pages)

    assert [unit.heading_path for unit in source_map.units] == [["Intro"], ["Intro", "Evidence"]]
    assert source_map.units[1].unit_id == "src-md-sec-0002"
    assert "Detailed evidence" in source_map.units[1].text


def test_source_access_resolves_pdf_physical_pages_not_printed_labels() -> None:
    source = _source("src-pdf", source_type="pdf", page_count=3)
    pages = [
        SourcePage("src-pdf", 1, "front matter", len("front matter"), "pypdf"),
        SourcePage("src-pdf", 2, "printed page one", len("printed page one"), "pypdf"),
        SourcePage("src-pdf", 3, "printed page two", len("printed page two"), "pypdf"),
    ]
    source_map = build_source_map(source, pages, printed_page_labels={1: "i", 2: "1", 3: "2"})

    with LocalTempDir() as tmp:
        store = SourceStore(tmp)
        store.save_result(_result(source, pages, source_map))
        packet = SourceAccessService(store).resolve_locators(
            [
                SourceLocator(
                    source_id="src-pdf",
                    locator_type="pdf_pages",
                    pdf_page_start=2,
                    pdf_page_end=3,
                )
            ]
        )[0]

    assert packet.pdf_page_start == 2
    assert packet.pdf_page_end == 3
    assert packet.printed_page_start == "1"
    assert "printed page one" in packet.text
    assert "front matter" not in packet.text


def test_source_access_rejects_oversized_pdf_request_by_default() -> None:
    source = _source("src-pdf", source_type="pdf")
    pages = [
        SourcePage("src-pdf", page, f"text {page}", len(f"text {page}"), "pypdf")
        for page in range(1, 6)
    ]
    source_map = build_source_map(source, pages)

    with LocalTempDir() as tmp:
        store = SourceStore(tmp)
        store.save_result(_result(source, pages, source_map))
        packet = SourceAccessService(
            store,
            config=SourceAccessConfig(max_pdf_pages_per_request=2),
        ).resolve_locators(
            [
                SourceLocator(
                    source_id="src-pdf",
                    locator_type="pdf_pages",
                    pdf_page_start=1,
                    pdf_page_end=5,
                )
            ]
        )[0]

    assert packet.text == ""
    assert "max_pdf_pages_per_request=2" in packet.warnings[0]


def test_pdf_source_map_keeps_empty_page_units_for_lazy_ocr() -> None:
    source = _source("src-pdf", source_type="pdf")
    pages = [
        SourcePage("src-pdf", 1, "readable page", len("readable page"), "pypdf"),
        SourcePage("src-pdf", 2, "", 0, "pypdf"),
    ]

    source_map = build_source_map(source, pages, printed_page_labels={1: "i", 2: "1"})

    assert [unit.pdf_page_start for unit in source_map.units] == [1, 2]
    assert source_map.units[1].printed_page_start == "1"
    assert source_map.units[1].text_quality == "low"


def test_source_access_lazy_ocrs_missing_pdf_page_and_persists_it() -> None:
    provider = FakePdfPageOcrProvider(
        [SourcePage("src-pdf", 2, "OCR recovered page two.", len("OCR recovered page two."), "ocr:tesseract")]
    )

    with LocalTempDir() as tmp:
        original = tmp / "uploaded.pdf"
        original.write_bytes(b"%PDF-pretend-for-fake-ocr-provider")
        source = _source("src-pdf", source_type="pdf", original_path=str(original), page_count=2)
        pages = [
            SourcePage("src-pdf", 1, "embedded page one", len("embedded page one"), "pypdf"),
            SourcePage("src-pdf", 2, "", 0, "pypdf"),
        ]
        source_map = build_source_map(source, pages, printed_page_labels={1: "i", 2: "1"})
        store = SourceStore(tmp / "source_store")
        store.save_result(_result(source, pages, source_map))

        packet = SourceAccessService(store, pdf_page_ocr_provider=provider).resolve_locators(
            [
                SourceLocator(
                    source_id="src-pdf",
                    locator_type="pdf_pages",
                    pdf_page_start=2,
                    pdf_page_end=2,
                )
            ]
        )[0]
        saved_pages = store.load_pages("src-pdf")
        saved_source = store.load_source("src-pdf")
        saved_original_exists = Path(saved_source.original_path).exists()

    assert provider.calls == [([2], "src-pdf")]
    assert "OCR recovered page two." in packet.text
    assert packet.printed_page_start == "1"
    assert any("Lazy OCR refreshed" in warning for warning in packet.warnings)
    assert saved_pages[1].text == "OCR recovered page two."
    assert Path(saved_source.original_path).name == "original.pdf"
    assert saved_original_exists


def _source(
    source_id: str,
    *,
    source_type: str,
    original_path: str | None = None,
    page_count: int = 1,
) -> SourceDocument:
    return SourceDocument(
        id=source_id,
        original_path=original_path or f"{source_id}.{source_type}",
        file_name=f"{source_id}.{source_type}",
        source_type=source_type,
        page_count=page_count,
        char_count=100,
        extraction_method="pypdf" if source_type == "pdf" else "plain_text",
        text_quality="readable",
        full_text_available=True,
        indexed=False,
    )


class LocalTempDir:
    def __init__(self) -> None:
        self.path = Path("test-output") / f"source-access-{uuid4().hex}"

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=False)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class FakePdfPageOcrProvider:
    def __init__(self, pages: list[SourcePage]) -> None:
        self._pages = pages
        self.calls: list[tuple[list[int], str]] = []

    def extract_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
        *,
        source_id: str,
    ) -> list[SourcePage]:
        assert Path(pdf_path).exists()
        self.calls.append((page_numbers, source_id))
        requested = set(page_numbers)
        return [page for page in self._pages if page.page_number in requested]


def _result(
    source: SourceDocument,
    pages: list[SourcePage],
    source_map,
) -> SourceIngestionResult:
    return SourceIngestionResult(
        source=source,
        pages=pages,
        chunks=[
            SourceChunk(
                id=f"{source.id}-chunk-0001",
                source_id=source.id,
                ordinal=1,
                page_start=1,
                page_end=1,
                text="\n".join(page.text for page in pages),
                char_count=sum(page.char_count for page in pages),
            )
        ],
        source_card=SourceCard(
            source_id=source.id,
            title=source.file_name,
            source_type=source.source_type,
            page_count=source.page_count,
            extraction_method=source.extraction_method,
            brief_summary="summary",
        ),
        indexed=False,
        full_text_available=True,
        source_map=source_map,
    )
