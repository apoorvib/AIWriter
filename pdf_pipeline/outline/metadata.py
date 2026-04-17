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


def read_page_labels(pdf_path: str | Path) -> dict[int, str] | None:
    """Return a mapping from pdf_page (1-indexed) to printed label string.

    Reads the PDF's /PageLabels dictionary per the PDF 1.7 spec §12.4.2.
    Returns None if /PageLabels is absent.
    """
    reader = PdfReader(str(pdf_path))
    root = reader.trailer["/Root"]
    if "/PageLabels" not in root:
        return None
    nums = root["/PageLabels"]["/Nums"]

    segments: list[tuple[int, dict]] = []
    for i in range(0, len(nums), 2):
        start_idx = int(nums[i])
        segment_dict = nums[i + 1]
        segments.append((start_idx, dict(segment_dict)))

    page_count = len(reader.pages)
    labels: dict[int, str] = {}

    for seg_i, (start_idx, seg) in enumerate(segments):
        next_start = segments[seg_i + 1][0] if seg_i + 1 < len(segments) else page_count
        style = seg.get("/S")
        style_name = str(style) if style is not None else None
        prefix = str(seg.get("/P", ""))
        first_num = int(seg.get("/St", 1))

        for offset, page_idx_0 in enumerate(range(start_idx, next_start)):
            number = first_num + offset
            label = _render_label(style_name, number, prefix)
            labels[page_idx_0 + 1] = label

    return labels


def resolve_printed_to_pdf_page(printed: str, labels: dict[int, str]) -> int | None:
    """Return the pdf_page (1-indexed) for the given printed label, or None."""
    target = printed.strip().lower()
    for pdf_page, label in labels.items():
        if label.strip().lower() == target:
            return pdf_page
    return None


def _render_label(style: str | None, number: int, prefix: str) -> str:
    """Render a page label per /PageLabels style tokens."""
    if style is None:
        return f"{prefix}" if prefix else ""
    s = style.lstrip("/")
    if s == "D":
        return f"{prefix}{number}"
    if s == "R":
        return f"{prefix}{_to_roman(number).upper()}"
    if s == "r":
        return f"{prefix}{_to_roman(number).lower()}"
    if s == "A":
        return f"{prefix}{_to_alpha(number).upper()}"
    if s == "a":
        return f"{prefix}{_to_alpha(number).lower()}"
    return f"{prefix}{number}"


def _to_roman(n: int) -> str:
    vals = [
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
        (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
        (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    ]
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def _to_alpha(n: int) -> str:
    if n < 1:
        return ""
    letter = chr(ord("a") + (n - 1) % 26)
    repeat = (n - 1) // 26 + 1
    return letter * repeat
