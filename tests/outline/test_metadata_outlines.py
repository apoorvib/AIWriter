"""Tests for Layer 1: /Outlines reader.

These tests build tiny in-memory PDFs with pypdf so we don't need pre-built
fixture binaries for basic outline-parsing coverage.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from pdf_pipeline.outline.metadata import read_pdf_outlines


def _build_pdf_with_outline(tmp_path: Path, outline: list[tuple[str, int, list]]) -> Path:
    """Create a PDF with `outline` entries; each is (title, pdf_page_1idx, children)."""
    writer = PdfWriter()
    max_page = 0
    def _collect_max(items: list[tuple[str, int, list]]) -> None:
        nonlocal max_page
        for title, page, children in items:
            max_page = max(max_page, page)
            _collect_max(children)
    _collect_max(outline)
    for _ in range(max_page):
        writer.add_blank_page(width=612, height=792)

    def _add(items: list[tuple[str, int, list]], parent=None) -> None:
        for title, page, children in items:
            bookmark = writer.add_outline_item(title, page - 1, parent=parent)
            if children:
                _add(children, parent=bookmark)

    _add(outline)
    path = tmp_path / "built.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_reads_flat_outline(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [("Chapter 1", 5, []), ("Chapter 2", 10, []), ("Chapter 3", 20, [])],
    )
    entries = read_pdf_outlines(str(pdf))
    assert len(entries) == 3
    assert [e.title for e in entries] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert [e.start_pdf_page for e in entries] == [5, 10, 20]
    assert all(e.level == 1 for e in entries)
    assert all(e.parent_id is None for e in entries)
    assert all(e.source == "pdf_outline" for e in entries)
    assert all(e.confidence == 1.0 for e in entries)


def test_reads_nested_outline(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [
            ("Chapter 1", 5, [
                ("Section 1.1", 6, []),
                ("Section 1.2", 8, []),
            ]),
            ("Chapter 2", 10, []),
        ],
    )
    entries = read_pdf_outlines(str(pdf))
    assert len(entries) == 4
    titles = [e.title for e in entries]
    assert titles == ["Chapter 1", "Section 1.1", "Section 1.2", "Chapter 2"]
    levels = [e.level for e in entries]
    assert levels == [1, 2, 2, 1]
    ch1 = entries[0]
    s11 = entries[1]
    s12 = entries[2]
    assert s11.parent_id == ch1.id
    assert s12.parent_id == ch1.id


def test_returns_empty_when_no_outline(tmp_path: Path):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    path = tmp_path / "plain.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    assert read_pdf_outlines(str(path)) == []


def test_ids_are_stable_and_unique(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [("Chapter 1", 5, [("Section 1.1", 6, [])]), ("Chapter 2", 10, [])],
    )
    entries = read_pdf_outlines(str(pdf))
    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids))
    entries_again = read_pdf_outlines(str(pdf))
    assert [e.id for e in entries_again] == ids
