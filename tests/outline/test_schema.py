import pytest

from pdf_pipeline.outline.schema import (
    DocumentOutline,
    OutlineEntry,
    SOURCE_TYPES,
)


def test_outline_entry_stores_fields():
    entry = OutlineEntry(
        id="ch1",
        title="Introduction",
        level=1,
        parent_id=None,
        start_pdf_page=17,
        end_pdf_page=32,
        printed_page="1",
        confidence=0.95,
        source="anchor_scan",
    )
    assert entry.id == "ch1"
    assert entry.title == "Introduction"
    assert entry.source == "anchor_scan"


def test_outline_entry_rejects_unknown_source():
    with pytest.raises(ValueError, match="unknown source"):
        OutlineEntry(
            id="x", title="x", level=1, parent_id=None,
            start_pdf_page=1, end_pdf_page=2,
            printed_page=None, confidence=1.0, source="made_up",
        )


def test_outline_entry_rejects_confidence_out_of_range():
    with pytest.raises(ValueError, match="confidence"):
        OutlineEntry(
            id="x", title="x", level=1, parent_id=None,
            start_pdf_page=None, end_pdf_page=None,
            printed_page=None, confidence=1.5, source="unresolved",
        )


def test_unresolved_entry_allows_null_pages():
    entry = OutlineEntry(
        id="ch3", title="Methods", level=1, parent_id=None,
        start_pdf_page=None, end_pdf_page=None,
        printed_page="47", confidence=0.0, source="unresolved",
    )
    assert entry.start_pdf_page is None


def test_document_outline_holds_entries():
    entry = OutlineEntry(
        id="ch1", title="A", level=1, parent_id=None,
        start_pdf_page=1, end_pdf_page=10,
        printed_page="1", confidence=1.0, source="pdf_outline",
    )
    outline = DocumentOutline(source_id="doc-42", version=1, entries=[entry])
    assert outline.source_id == "doc-42"
    assert outline.version == 1
    assert outline.entries == [entry]


def test_source_types_enumerated():
    assert "pdf_outline" in SOURCE_TYPES
    assert "page_labels" in SOURCE_TYPES
    assert "anchor_scan" in SOURCE_TYPES
    assert "unresolved" in SOURCE_TYPES
