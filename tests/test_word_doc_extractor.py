from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from pdf_pipeline.document_reader import DocumentReader
from pdf_pipeline.extractors import InvalidWordDocumentError, WordDocExtractor


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _table(rows: list[list[str]]) -> str:
    row_xml = []
    for row in rows:
        cells = "".join(f"<w:tc>{_paragraph(cell)}</w:tc>" for cell in row)
        row_xml.append(f"<w:tr>{cells}</w:tr>")
    return f"<w:tbl>{''.join(row_xml)}</w:tbl>"


def _write_docx(path: Path, body_xml: str) -> None:
    document_xml = f"""
    <w:document xmlns:w="{WORD_NS}">
      <w:body>
        {body_xml}
      </w:body>
    </w:document>
    """
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


def test_extracts_docx_paragraphs_as_one_logical_page(tmp_path: Path) -> None:
    docx_path = tmp_path / "assignment.docx"
    _write_docx(docx_path, _paragraph("Essay prompt") + _paragraph("Use two sources."))

    result = WordDocExtractor().extract(docx_path)

    assert result.source_path == str(docx_path)
    assert result.page_count == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].text == "Essay prompt\n\nUse two sources."
    assert result.pages[0].char_count == len(result.pages[0].text)
    assert result.pages[0].extraction_method == "docx"


def test_extracts_docx_tables_in_reading_order(tmp_path: Path) -> None:
    docx_path = tmp_path / "source_notes.docx"
    _write_docx(
        docx_path,
        _paragraph("Source notes")
        + _table(
            [
                ["Claim", "Evidence"],
                ["Policy changed", "Report page 4"],
            ]
        ),
    )

    result = WordDocExtractor().extract(docx_path)

    assert result.pages[0].text == (
        "Source notes\n\n"
        "Claim\tEvidence\n"
        "Policy changed\tReport page 4"
    )


def test_document_reader_routes_docx_files(tmp_path: Path) -> None:
    docx_path = tmp_path / "task.docx"
    _write_docx(docx_path, _paragraph("Read chapter 3."))

    result = DocumentReader().extract(docx_path)

    assert result.pages[0].text == "Read chapter 3."
    assert result.pages[0].extraction_method == "docx"


def test_rejects_legacy_doc_files(tmp_path: Path) -> None:
    doc_path = tmp_path / "legacy.doc"
    doc_path.write_bytes(b"old-word-format")

    with pytest.raises(ValueError, match="Legacy .doc files are not supported"):
        DocumentReader().extract(doc_path)


def test_rejects_corrupt_docx(tmp_path: Path) -> None:
    docx_path = tmp_path / "corrupt.docx"
    docx_path.write_bytes(b"not-a-zip")

    with pytest.raises(InvalidWordDocumentError):
        WordDocExtractor().extract(docx_path)


def test_rejects_docx_missing_main_document_xml(tmp_path: Path) -> None:
    docx_path = tmp_path / "missing_document_xml.docx"
    with ZipFile(docx_path, "w") as archive:
        archive.writestr("word/other.xml", "<xml />")

    with pytest.raises(InvalidWordDocumentError):
        WordDocExtractor().extract(docx_path)
