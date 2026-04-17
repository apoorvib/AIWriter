from pdf_pipeline.outline.anchor_scan import pick_anchor_candidates
from pdf_pipeline.outline.entry_extraction import RawEntry


def _e(title: str, pp: str = "1", level: int = 1) -> RawEntry:
    return RawEntry(title=title, level=level, printed_page=pp)


def test_prefers_longer_titles_with_chapter_tokens():
    entries = [
        _e("Introduction", "1"),
        _e("Chapter 1: Origins of the Problem", "5"),
        _e("A", "7"),
        _e("Chapter 2: The Methods We Use", "25"),
        _e("Notes", "100"),
    ]
    picks = pick_anchor_candidates(entries, k=3)
    titles = [p.title for p in picks]
    assert "Chapter 1: Origins of the Problem" in titles
    assert "Chapter 2: The Methods We Use" in titles
    assert "A" not in titles


def test_drops_duplicate_titles():
    entries = [
        _e("Chapter 1: Introduction", "1"),
        _e("Chapter 1: Introduction", "50"),
        _e("Chapter 2: Review", "10"),
    ]
    picks = pick_anchor_candidates(entries, k=3)
    titles = [p.title for p in picks]
    assert titles.count("Chapter 1: Introduction") <= 1


def test_returns_empty_when_no_entries():
    assert pick_anchor_candidates([], k=3) == []


def test_caps_at_k():
    entries = [_e(f"Chapter {i}: Topic {i} Longer Title", str(i * 10)) for i in range(1, 10)]
    picks = pick_anchor_candidates(entries, k=3)
    assert len(picks) == 3
