"""Layer 1: read structural PDF metadata (/Outlines, /PageLabels)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from pdf_pipeline.outline.schema import OutlineEntry


def read_pdf_outlines(pdf_path: str | Path) -> list[OutlineEntry]:
    """Extract the embedded PDF outline (/Outlines) as OutlineEntry records.

    Returns an empty list if the PDF has no outline. End pages are left as
    None; Layer 4 (range_assignment) fills them in.
    """
    reader = PdfReader(str(pdf_path))
    outline_root = reader.outline
    if not outline_root:
        return []

    entries: list[OutlineEntry] = []
    _walk(outline_root, reader, entries, level=1, parent_id=None, path_prefix="o")
    return entries


def _walk(
    items: list[Any],
    reader: PdfReader,
    entries: list[OutlineEntry],
    level: int,
    parent_id: str | None,
    path_prefix: str,
) -> None:
    """Walk pypdf's nested outline list.

    pypdf represents the outline as a list where top-level entries are
    Destination-like objects and a nested list immediately following an entry
    contains that entry's children.
    """
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, list):
            i += 1
            continue

        entry_id = f"{path_prefix}{len(entries)}"
        title = str(getattr(item, "title", "")) or "(untitled)"
        try:
            page_idx = reader.get_destination_page_number(item)
        except Exception:
            i += 1
            continue
        pdf_page = page_idx + 1

        entry = OutlineEntry(
            id=entry_id,
            title=title,
            level=level,
            parent_id=parent_id,
            start_pdf_page=pdf_page,
            end_pdf_page=None,
            printed_page=None,
            confidence=1.0,
            source="pdf_outline",
        )
        entries.append(entry)

        if i + 1 < len(items) and isinstance(items[i + 1], list):
            _walk(items[i + 1], reader, entries, level + 1, entry.id, path_prefix)
            i += 2
        else:
            i += 1
