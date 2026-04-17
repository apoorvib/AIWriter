from pdf_pipeline.outline.anchor_scan import resolve_entries
from pdf_pipeline.outline.entry_extraction import RawEntry


def _e(title: str, pp: str, level: int = 1) -> RawEntry:
    return RawEntry(title=title, level=level, printed_page=pp)


def test_resolved_entries_get_pdf_pages_and_confidence():
    entries = [
        _e("Chapter 1: Origins of the Problem", "1"),
        _e("Chapter 2: Methods Explained Fully", "25"),
    ]
    pages = {
        17: "\n\nChapter 1: Origins of the Problem\n\nbody",
        41: "\n\nChapter 2: Methods Explained Fully\n\nbody",
    }
    resolved = resolve_entries(entries, pages, max_offset=100)

    assert len(resolved) == 2
    ch1, ch2 = resolved
    assert ch1.start_pdf_page == 17
    assert ch2.start_pdf_page == 41
    assert ch1.source == "anchor_scan"
    assert ch2.source == "anchor_scan"
    assert ch1.confidence > 0.5


def test_unresolved_entries_when_no_offset_found():
    entries = [_e("Nonexistent Chapter", "1")]
    pages = {1: "alpha", 2: "beta"}
    resolved = resolve_entries(entries, pages, max_offset=10)
    assert len(resolved) == 1
    assert resolved[0].start_pdf_page is None
    assert resolved[0].end_pdf_page is None
    assert resolved[0].source == "unresolved"
    assert resolved[0].confidence == 0.0


def test_low_confidence_for_entry_that_doesnt_cross_validate():
    entries = [
        _e("Chapter 1: Origins of the Problem", "1"),
        _e("Chapter 2: Also Here", "25"),
        _e("Chapter 3: Broken Reference", "50"),  # Doesn't exist at predicted page
    ]
    pages = {
        17: "Chapter 1: Origins of the Problem\n\nbody",
        41: "Chapter 2: Also Here\n\nbody",
        66: "Totally different content here nothing to match",
    }
    resolved = resolve_entries(entries, pages, max_offset=100)
    # Chapter 3 should still get a pdf_page from the global offset (66) but
    # with lower confidence since its title doesn't appear there.
    ch3 = resolved[2]
    assert ch3.start_pdf_page == 66
    assert ch3.confidence <= 0.6
