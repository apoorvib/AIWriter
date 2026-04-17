from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from pdf_pipeline.outline.metadata import read_page_labels, resolve_printed_to_pdf_page


def _write_pdf(tmp_path: Path, labels_nums: list) -> Path:
    writer = PdfWriter()
    for _ in range(30):
        writer.add_blank_page(width=612, height=792)
    labels_dict = DictionaryObject({NameObject("/Nums"): ArrayObject(labels_nums)})
    writer._root_object[NameObject("/PageLabels")] = labels_dict
    path = tmp_path / "labelled.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_reads_arabic_labels(tmp_path: Path):
    nums = [
        NumberObject(0),
        DictionaryObject({NameObject("/S"): NameObject("/D"), NameObject("/St"): NumberObject(1)}),
    ]
    pdf = _write_pdf(tmp_path, nums)
    labels = read_page_labels(str(pdf))
    assert labels[1] == "1"
    assert labels[10] == "10"
    assert labels[30] == "30"


def test_reads_roman_then_arabic_labels(tmp_path: Path):
    nums = [
        NumberObject(0),
        DictionaryObject({NameObject("/S"): NameObject("/r")}),
        NumberObject(5),
        DictionaryObject({NameObject("/S"): NameObject("/D"), NameObject("/St"): NumberObject(1)}),
    ]
    pdf = _write_pdf(tmp_path, nums)
    labels = read_page_labels(str(pdf))
    assert labels[1] == "i"
    assert labels[5] == "v"
    assert labels[6] == "1"
    assert labels[30] == "25"


def test_returns_none_when_absent(tmp_path: Path):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    path = tmp_path / "nolabel.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    assert read_page_labels(str(path)) is None


def test_resolve_printed_to_pdf_page():
    labels = {1: "i", 2: "ii", 3: "iii", 4: "1", 5: "2", 6: "3"}
    assert resolve_printed_to_pdf_page("1", labels) == 4
    assert resolve_printed_to_pdf_page("iii", labels) == 3
    assert resolve_printed_to_pdf_page("99", labels) is None
