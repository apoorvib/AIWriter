from __future__ import annotations
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from pdf_pipeline.extractors.base import EncryptedPdfError, InvalidPdfError, PdfExtractor
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.text_utils import normalize_text


class PyPdfExtractor(PdfExtractor):
    """Baseline text-native PDF extractor backed by pypdf."""

    def extract(self, pdf_path: str | Path) -> DocumentExtractionResult:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a .pdf file, got: {path.suffix}")

        try:
            reader = PdfReader(str(path))
        except PdfReadError as exc:
            raise InvalidPdfError(f"Could not read PDF: {path}") from exc

        if reader.is_encrypted:
            raise EncryptedPdfError(f"Encrypted PDF is not supported: {path}")

        pages: list[PageText] = []
        for idx, page in enumerate(reader.pages, start=1):
            try:
                raw_text = page.extract_text() or ""
            except (PdfReadError, FileNotDecryptedError) as exc:
                raise InvalidPdfError(f"Failed to extract text from page {idx}") from exc

            text = normalize_text(raw_text)
            pages.append(
                PageText(
                    page_number=idx,
                    text=text,
                    char_count=len(text),
                    extraction_method="pypdf",
                )
            )

        return DocumentExtractionResult(
            source_path=str(path),
            page_count=len(reader.pages),
            pages=pages,
        )
