from pdf_pipeline.outline.anchor_scan import (
    MatchResult,
    find_anchor_page,
    is_heading_like,
)
from pdf_pipeline.outline.entry_extraction import RawEntry


def _pages(mapping: dict[int, str]) -> dict[int, str]:
    return mapping


def test_finds_title_on_chapter_opening():
    pages = {
        1: "copyright notice\nall rights reserved",
        2: "dedication",
        3: "\n\nChapter 1: Origins of the Problem\n\nWe begin our study by ...",
        4: "Chapter 1: Origins of the Problem  continued body text here.",
    }
    anchor = RawEntry(title="Chapter 1: Origins of the Problem", level=1, printed_page="1")
    result = find_anchor_page(anchor, pages, max_offset=10)
    assert result == MatchResult(pdf_page=3, pass_=("A"))


def test_falls_back_to_pass_b_when_only_running_headers():
    pages = {
        1: "copyright",
        2: "dedication",
        # First occurrence is a running header, not an isolated chapter opening.
        3: "Chapter 1: Origins of the Problem    body that is long enough to fill the line",
        4: "Chapter 1: Origins of the Problem    more body body body body body body body",
    }
    anchor = RawEntry(title="Chapter 1: Origins of the Problem", level=1, printed_page="1")
    result = find_anchor_page(anchor, pages, max_offset=10)
    assert result.pdf_page == 3
    assert result.pass_ == "B"


def test_returns_none_when_not_found_in_range():
    pages = {1: "alpha", 2: "beta", 3: "gamma"}
    anchor = RawEntry(title="Chapter 9: Nowhere", level=1, printed_page="9")
    assert find_anchor_page(anchor, pages, max_offset=3) is None


def test_is_heading_like_detects_isolated_top_line():
    page = "\n\nChapter 1: Origins\n\nWe begin..."
    assert is_heading_like(page, "Chapter 1: Origins") is True


def test_is_heading_like_rejects_inline_occurrence():
    page = "This chapter, the famous 'Chapter 1: Origins', introduces the topic in detail and ..."
    assert is_heading_like(page, "Chapter 1: Origins") is False


def test_is_heading_like_handles_empty_inputs():
    assert is_heading_like("", "Chapter 1") is False
    assert is_heading_like("some page text", "") is False


def test_total_pages_extends_scan_past_sparse_text():
    # pages_text only has page 40 (OCR gap on intermediate pages), but
    # total_pages says the doc has 200. Without the override the scan would
    # stop at 40's neighborhood; with it the anchor at 40 is still found.
    pages = {40: "\n\nChapter 3: Far Away\n\nbody"}
    anchor = RawEntry(title="Chapter 3: Far Away", level=1, printed_page="20")
    result = find_anchor_page(anchor, pages, max_offset=100, total_pages=200)
    assert result is not None
    assert result.pdf_page == 40
