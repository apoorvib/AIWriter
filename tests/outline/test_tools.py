from pathlib import Path

import pytest
from pypdf import PdfWriter

from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry
from pdf_pipeline.outline.storage import OutlineStore
from pdf_pipeline.outline.tools import SectionLookupError, get_section, list_outline


def _write_blank_pdf(path: Path, n_pages: int) -> None:
    writer = PdfWriter()
    for i in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as fh:
        writer.write(fh)


def _entry(id_: str, start: int | None, end: int | None) -> OutlineEntry:
    return OutlineEntry(
        id=id_, title=f"e-{id_}", level=1, parent_id=None,
        start_pdf_page=start, end_pdf_page=end,
        printed_page=None, confidence=1.0,
        source="pdf_outline" if start else "unresolved",
    )


def _seed_outline(store: OutlineStore, source_id: str, entries: list[OutlineEntry]) -> None:
    store.save(DocumentOutline(source_id=source_id, version=1, entries=entries))


def test_list_outline_returns_entries(tmp_path: Path):
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("a", 1, 5), _entry("b", 6, 10)])
    entries = list_outline("s1", store=store)
    assert [e.id for e in entries] == ["a", "b"]


def test_get_section_returns_concatenated_text(tmp_path: Path):
    pdf_path = tmp_path / "s1.pdf"
    _write_blank_pdf(pdf_path, 10)
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("a", 1, 3), _entry("b", 4, 10)])

    # Fake per-page extractor so we don't need real text.
    class FakeExtractor:
        def extract_page_text(self, p: str, n: int) -> str:
            return f"page-{n}"

    text = get_section("s1", "b", pdf_path=str(pdf_path), store=store, extractor=FakeExtractor())
    assert text == "page-4\npage-5\npage-6\npage-7\npage-8\npage-9\npage-10"


def test_get_section_rejects_unresolved_entry(tmp_path: Path):
    pdf_path = tmp_path / "s1.pdf"
    _write_blank_pdf(pdf_path, 5)
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("u", None, None)])

    with pytest.raises(SectionLookupError, match="unresolved"):
        get_section("s1", "u", pdf_path=str(pdf_path), store=store)


def test_get_section_rejects_unknown_entry(tmp_path: Path):
    pdf_path = tmp_path / "s1.pdf"
    _write_blank_pdf(pdf_path, 5)
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("a", 1, 5)])

    with pytest.raises(SectionLookupError, match="not found"):
        get_section("s1", "missing", pdf_path=str(pdf_path), store=store)
