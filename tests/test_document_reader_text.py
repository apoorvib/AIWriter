from __future__ import annotations

from pdf_pipeline.document_reader import DocumentReader
from tests.task_spec._tmp import LocalTempDir


def test_document_reader_reads_plain_text_files() -> None:
    with LocalTempDir() as tmp_path:
        path = tmp_path / "notes.txt"
        path.write_text("Line one.\nLine two.", encoding="utf-8")

        result = DocumentReader().extract(path)

    assert result.page_count == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].text == "Line one.\nLine two."
    assert result.pages[0].extraction_method == "plain_text"


def test_document_reader_reads_markdown_files() -> None:
    with LocalTempDir() as tmp_path:
        path = tmp_path / "notes.md"
        path.write_text("# Heading\n\nBody.", encoding="utf-8")

        result = DocumentReader().extract(path)

    assert result.page_count == 1
    assert result.pages[0].text == "# Heading\n\nBody."


def test_document_reader_reads_note_files() -> None:
    with LocalTempDir() as tmp_path:
        path = tmp_path / "class.notes"
        path.write_text("Lecture note:\nheat islands and housing.", encoding="utf-8")

        result = DocumentReader().extract(path)

    assert result.page_count == 1
    assert result.pages[0].text.startswith("Lecture note:")
    assert result.pages[0].extraction_method == "plain_text"
