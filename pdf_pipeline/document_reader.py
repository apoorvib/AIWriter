from __future__ import annotations

from pathlib import Path

from pdf_pipeline.extractors.pypdf_extractor import PyPdfExtractor
from pdf_pipeline.extractors.word_doc_extractor import WordDocExtractor
from pdf_pipeline.models import DocumentExtractionResult


class DocumentReader:
    """Route supported source documents to the right text extractor."""

    def extract(self, document_path: str | Path) -> DocumentExtractionResult:
        path = Path(document_path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return PyPdfExtractor().extract(path)
        if suffix == ".docx":
            return WordDocExtractor().extract(path)
        if suffix == ".doc":
            raise ValueError("Legacy .doc files are not supported. Convert the file to .docx first.")

        raise ValueError(f"Unsupported document type: {path.suffix}")
