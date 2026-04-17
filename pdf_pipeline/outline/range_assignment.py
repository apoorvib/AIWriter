"""Layer 4: fill in end_pdf_page for each resolved entry."""
from __future__ import annotations

from dataclasses import replace

from pdf_pipeline.outline.schema import OutlineEntry


def assign_end_pages(entries: list[OutlineEntry], total_pages: int) -> list[OutlineEntry]:
    """Return a new list with end_pdf_page filled in for resolved entries.

    For each entry at level L with start S, end = (start of next entry
    with level <= L) - 1. If there is no such following entry, end =
    total_pages. Unresolved entries (start_pdf_page is None) are left
    untouched.
    """
    result: list[OutlineEntry] = []
    for i, entry in enumerate(entries):
        if entry.start_pdf_page is None:
            result.append(entry)
            continue

        end = total_pages
        for j in range(i + 1, len(entries)):
            nxt = entries[j]
            if nxt.start_pdf_page is None:
                continue
            if nxt.level <= entry.level:
                end = nxt.start_pdf_page - 1
                break

        result.append(replace(entry, end_pdf_page=end))

    return result
