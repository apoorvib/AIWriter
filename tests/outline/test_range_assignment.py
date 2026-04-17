from pdf_pipeline.outline.range_assignment import assign_end_pages
from pdf_pipeline.outline.schema import OutlineEntry


def _entry(id_: str, title: str, level: int, start: int | None, parent: str | None = None) -> OutlineEntry:
    return OutlineEntry(
        id=id_, title=title, level=level, parent_id=parent,
        start_pdf_page=start, end_pdf_page=None, printed_page=None,
        confidence=1.0, source="pdf_outline" if start else "unresolved",
    )


def test_top_level_ranges_are_derived_from_next_sibling():
    entries = [
        _entry("c1", "Ch 1", 1, 5),
        _entry("c2", "Ch 2", 1, 20),
        _entry("c3", "Ch 3", 1, 40),
    ]
    out = assign_end_pages(entries, total_pages=60)
    assert out[0].end_pdf_page == 19
    assert out[1].end_pdf_page == 39
    assert out[2].end_pdf_page == 60


def test_subsection_end_is_next_sibling_minus_one():
    entries = [
        _entry("c1", "Ch 1", 1, 5),
        _entry("s11", "1.1", 2, 5, parent="c1"),
        _entry("s12", "1.2", 2, 10, parent="c1"),
        _entry("c2", "Ch 2", 1, 20),
    ]
    out = assign_end_pages(entries, total_pages=30)
    # section 1.1 ends before 1.2
    assert out[1].end_pdf_page == 9
    # section 1.2 ends at chapter 2 - 1 (parent's effective end)
    assert out[2].end_pdf_page == 19
    # chapter 1 spans 5..19
    assert out[0].end_pdf_page == 19


def test_unresolved_entries_keep_null_ranges():
    entries = [
        _entry("c1", "Ch 1", 1, 5),
        _entry("c2", "Ch 2", 1, None),  # unresolved
        _entry("c3", "Ch 3", 1, 40),
    ]
    out = assign_end_pages(entries, total_pages=60)
    assert out[0].end_pdf_page == 39  # skips unresolved
    assert out[1].end_pdf_page is None
    assert out[2].end_pdf_page == 60
