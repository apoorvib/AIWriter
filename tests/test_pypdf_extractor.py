from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdf_pipeline.extractors import EncryptedPdfError, InvalidPdfError, PyPdfExtractor


def _add_text_page(writer: PdfWriter, text: str) -> None:
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)  # noqa: SLF001 - supported pypdf low-level API
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): font_ref,
                }
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def _write_text_pdf(path: Path) -> None:
    writer = PdfWriter()
    _add_text_page(writer, "Hello from page 1")
    _add_text_page(writer, "Hello from page 2")
    with path.open("wb") as handle:
        writer.write(handle)


def test_extracts_multi_page_text_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _write_text_pdf(pdf_path)

    result = PyPdfExtractor().extract(pdf_path)

    assert result.page_count == 2
    assert [p.page_number for p in result.pages] == [1, 2]
    assert "Hello from page 1" in result.pages[0].text
    assert "Hello from page 2" in result.pages[1].text
    assert [p.extraction_method for p in result.pages] == ["pypdf", "pypdf"]


def test_emits_empty_page_text_when_page_has_no_content(tmp_path: Path) -> None:
    pdf_path = tmp_path / "empty_page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    result = PyPdfExtractor().extract(pdf_path)

    assert result.page_count == 1
    assert result.pages[0].text == ""
    assert result.pages[0].char_count == 0


def test_rejects_corrupt_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(b"this-is-not-a-real-pdf")

    with pytest.raises(InvalidPdfError):
        PyPdfExtractor().extract(pdf_path)


def test_rejects_encrypted_pdf(tmp_path: Path) -> None:
    input_pdf = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    _add_text_page(writer, "secret text")
    writer.encrypt("pass123")
    with input_pdf.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(EncryptedPdfError):
        PyPdfExtractor().extract(input_pdf)


def test_returns_deterministic_page_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ordered.pdf"
    _write_text_pdf(pdf_path)

    first = PyPdfExtractor().extract(pdf_path)
    second = PyPdfExtractor().extract(pdf_path)

    first_page_numbers = [page.page_number for page in first.pages]
    second_page_numbers = [page.page_number for page in second.pages]
    assert first_page_numbers == second_page_numbers == [1, 2]
    assert [page.text for page in first.pages] == [page.text for page in second.pages]
