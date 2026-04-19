"""Resolve RawEntry records against /PageLabels (Layer 1.5).

When a PDF carries a /PageLabels dictionary, the printed page number for
each TOC entry can be mapped to its pdf_page directly, without the
forward-scan heuristics in anchor_scan. Entries whose printed_page does
not appear in the label map are emitted as source="unresolved" so the
pipeline can optionally fall back to anchor scan for them.
"""
from __future__ import annotations

from pdf_pipeline.outline._hierarchy import parent_for, push_ancestor
from pdf_pipeline.outline.entry_extraction import RawEntry
from pdf_pipeline.outline.schema import OutlineEntry

_CONFIDENCE_LABEL_MATCH = 0.95


def resolve_entries_via_labels(
    entries: list[RawEntry], labels: dict[int, str]
) -> list[OutlineEntry]:
    """Return one OutlineEntry per raw entry, resolved against the label map.

    Label matching is case-insensitive and strips surrounding whitespace.
    Entries whose printed_page has no match become source="unresolved"
    with confidence 0.0.
    """
    inverted: dict[str, int] = {}
    for pdf_page, label in labels.items():
        key = label.strip().lower()
        if key and key not in inverted:
            inverted[key] = pdf_page

    resolved: list[OutlineEntry] = []
    ancestors: list[tuple[int, str]] = []

    for i, raw in enumerate(entries):
        target = raw.printed_page.strip().lower() if raw.printed_page else ""
        pdf_page = inverted.get(target)

        if pdf_page is None:
            entry = OutlineEntry(
                id=f"u{i}",
                title=raw.title,
                level=raw.level,
                parent_id=parent_for(raw.level, ancestors),
                start_pdf_page=None,
                end_pdf_page=None,
                printed_page=raw.printed_page,
                confidence=0.0,
                source="unresolved",
            )
        else:
            entry = OutlineEntry(
                id=f"l{i}",
                title=raw.title,
                level=raw.level,
                parent_id=parent_for(raw.level, ancestors),
                start_pdf_page=pdf_page,
                end_pdf_page=None,
                printed_page=raw.printed_page,
                confidence=_CONFIDENCE_LABEL_MATCH,
                source="page_labels",
            )

        resolved.append(entry)
        push_ancestor(ancestors, raw.level, entry.id)

    return resolved
