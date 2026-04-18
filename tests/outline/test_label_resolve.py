from pdf_pipeline.outline.entry_extraction import RawEntry
from pdf_pipeline.outline.label_resolve import resolve_entries_via_labels


def _e(title: str, pp: str, level: int = 1) -> RawEntry:
    return RawEntry(title=title, level=level, printed_page=pp)


def test_resolves_each_entry_via_inverted_label_map():
    # front matter uses roman numerals, body uses arabic
    labels = {
        1: "i",
        2: "ii",
        3: "iii",
        4: "1",
        5: "2",
        6: "3",
        7: "4",
    }
    entries = [
        _e("Preface", "ii"),
        _e("Chapter 1", "1"),
        _e("Chapter 2", "3"),
    ]
    resolved = resolve_entries_via_labels(entries, labels)

    assert [r.start_pdf_page for r in resolved] == [2, 4, 6]
    assert all(r.source == "page_labels" for r in resolved)
    assert all(r.confidence == 0.95 for r in resolved)


def test_unmatched_printed_pages_become_unresolved():
    labels = {1: "1", 2: "2", 3: "3"}
    entries = [
        _e("Chapter 1", "1"),
        _e("Chapter Missing", "99"),
    ]
    resolved = resolve_entries_via_labels(entries, labels)

    assert resolved[0].source == "page_labels"
    assert resolved[0].start_pdf_page == 1
    assert resolved[1].source == "unresolved"
    assert resolved[1].start_pdf_page is None
    assert resolved[1].confidence == 0.0


def test_parent_ids_are_threaded_across_levels():
    labels = {1: "1", 2: "2", 3: "3", 4: "4"}
    entries = [
        _e("Chapter 1", "1", level=1),
        _e("1.1 Sub", "2", level=2),
        _e("1.2 Sub", "3", level=2),
        _e("Chapter 2", "4", level=1),
    ]
    resolved = resolve_entries_via_labels(entries, labels)

    c1, s11, s12, c2 = resolved
    assert c1.parent_id is None
    assert s11.parent_id == c1.id
    assert s12.parent_id == c1.id
    assert c2.parent_id is None


def test_label_matching_is_case_insensitive_and_strips_whitespace():
    labels = {1: "  IV  ", 2: "A-1"}
    entries = [_e("X", "iv"), _e("Y", "a-1")]
    resolved = resolve_entries_via_labels(entries, labels)
    assert resolved[0].start_pdf_page == 1
    assert resolved[1].start_pdf_page == 2
