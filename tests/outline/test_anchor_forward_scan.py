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
