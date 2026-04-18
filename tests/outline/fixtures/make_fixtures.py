"""Regenerate the outline fixture PDFs.

Run: python tests/outline/fixtures/make_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter


HERE = Path(__file__).parent


def make_born_digital_with_outlines() -> Path:
    writer = PdfWriter()
    for _ in range(30):
        writer.add_blank_page(width=612, height=792)
    writer.add_outline_item("Chapter 1: Origins", 4)  # pdf_page 5
    writer.add_outline_item("Chapter 2: Methods", 14)  # pdf_page 15
    writer.add_outline_item("Chapter 3: Results", 24)  # pdf_page 25
    path = HERE / "born_digital_with_outlines.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def make_article_no_toc() -> Path:
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=612, height=792)
    path = HERE / "article_no_toc.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


if __name__ == "__main__":
    for fn in [make_born_digital_with_outlines, make_article_no_toc]:
        out = fn()
        print(f"wrote {out}")
