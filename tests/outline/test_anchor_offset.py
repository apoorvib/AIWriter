from pdf_pipeline.outline.anchor_scan import derive_offset
from pdf_pipeline.outline.entry_extraction import RawEntry


def _e(title: str, pp: str) -> RawEntry:
    return RawEntry(title=title, level=1, printed_page=pp)


def test_derives_offset_from_first_validated_anchor():
    entries = [
        _e("Chapter 1: Origins and Beginnings", "1"),
        _e("Chapter 2: Methods Explained Clearly", "25"),
        _e("Chapter 3: Results and Discussion", "60"),
    ]
    # Offset = 16 (front matter = 16 pages of romans etc.)
    pages = {
        1: "copyright", 2: "dedication", 3: "preface",
        # chapter opens
        17: "\n\nChapter 1: Origins and Beginnings\n\nbody",
        41: "\n\nChapter 2: Methods Explained Clearly\n\nbody",
        76: "\n\nChapter 3: Results and Discussion\n\nbody",
    }
    result = derive_offset(entries, pages, max_offset=100)
    assert result is not None
    assert result.offset == 16
    assert result.validated_count >= 2


def test_returns_none_when_no_anchor_matches():
    entries = [_e("Nonexistent Chapter Title Goes Here", "1")]
    pages = {1: "alpha", 2: "beta", 3: "gamma"}
    assert derive_offset(entries, pages, max_offset=10) is None


def test_rejects_offset_when_validators_disagree():
    entries = [
        _e("Chapter 1: Origins and Beginnings", "1"),
        _e("Chapter 2: Not Actually Anywhere", "25"),
        _e("Chapter 3: Also Not Present Here", "60"),
    ]
    # Only chapter 1 appears where expected; others don't exist in body.
    pages = {
        17: "\n\nChapter 1: Origins and Beginnings\n\nbody",
    }
    assert derive_offset(entries, pages, max_offset=100) is None
