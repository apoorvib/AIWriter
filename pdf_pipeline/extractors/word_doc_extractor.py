from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pdf_pipeline.extractors.base import InvalidWordDocumentError
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.text_utils import normalize_text


WORD_DOCUMENT_XML = "word/document.xml"
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class WordDocExtractor:
    """Text extractor for modern Word .docx files.

    Word documents do not store stable page boundaries in the file format, so
    extracted content is returned as one logical page.
    """

    def extract(self, docx_path: str | Path) -> DocumentExtractionResult:
        path = Path(docx_path)
        if not path.exists():
            raise FileNotFoundError(f"Word document not found: {path}")
        if path.suffix.lower() != ".docx":
            raise ValueError(f"Expected a .docx file, got: {path.suffix}")

        document_xml = self._read_document_xml(path)
        text = normalize_text(_extract_body_text(document_xml))

        page = PageText(
            page_number=1,
            text=text,
            char_count=len(text),
            extraction_method="docx",
        )
        return DocumentExtractionResult(
            source_path=str(path),
            page_count=1,
            pages=[page],
        )

    def _read_document_xml(self, path: Path) -> bytes:
        try:
            with ZipFile(path) as archive:
                try:
                    return archive.read(WORD_DOCUMENT_XML)
                except KeyError as exc:
                    raise InvalidWordDocumentError(f"Missing {WORD_DOCUMENT_XML}: {path}") from exc
        except BadZipFile as exc:
            raise InvalidWordDocumentError(f"Could not read Word document: {path}") from exc


def _extract_body_text(document_xml: bytes) -> str:
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise InvalidWordDocumentError("Word document XML is malformed.") from exc

    body = root.find(f"{{{WORD_NAMESPACE}}}body")
    if body is None:
        raise InvalidWordDocumentError("Word document XML is missing a body.")

    blocks: list[str] = []
    for child in body:
        name = _local_name(child.tag)
        if name == "p":
            paragraph = _extract_paragraph_text(child)
            if paragraph:
                blocks.append(paragraph)
        elif name == "tbl":
            table = _extract_table_text(child)
            if table:
                blocks.append(table)

    return "\n\n".join(blocks)


def _extract_table_text(table: ElementTree.Element) -> str:
    rows: list[str] = []
    for row in _children_by_local_name(table, "tr"):
        cells: list[str] = []
        for cell in _children_by_local_name(row, "tc"):
            paragraphs = [
                _extract_paragraph_text(paragraph)
                for paragraph in _children_by_local_name(cell, "p")
            ]
            cells.append("\n".join(paragraph for paragraph in paragraphs if paragraph))
        row_text = "\t".join(cells).strip()
        if row_text:
            rows.append(row_text)
    return "\n".join(rows)


def _extract_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        name = _local_name(element.tag)
        if name == "t" and element.text:
            parts.append(element.text)
        elif name == "tab":
            parts.append("\t")
        elif name in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _children_by_local_name(element: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
    return [child for child in element if _local_name(child.tag) == local_name]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
