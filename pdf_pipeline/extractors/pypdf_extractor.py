from __future__ import annotations
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from pdf_pipeline.extractors.base import EncryptedPdfError, InvalidPdfError, PdfExtractor
from pdf_pipeline.models import DocumentExtractionResult, PageText
from pdf_pipeline.text_utils import normalize_text


class PyPdfExtractor(PdfExtractor):
    """Baseline text-native PDF extractor backed by pypdf."""

    def __init__(self, start_page: int = 1, max_pages: int | None = None) -> None:
        if start_page < 1:
            raise ValueError(f"start_page must be >= 1, got: {start_page}")
        if max_pages is not None and max_pages < 1:
            raise ValueError(f"max_pages must be >= 1, got: {max_pages}")
        self.start_page = start_page
        self.max_pages = max_pages

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
            # Some PDFs are flagged as encrypted but are still readable with an
            # empty password. Try that path before rejecting the file.
            try:
                reader.decrypt("")
            except Exception:
                pass

        try:
            page_count = len(reader.pages)
        except FileNotDecryptedError as exc:
            raise EncryptedPdfError(f"Encrypted PDF is not supported: {path}") from exc
        except PdfReadError as exc:
            if reader.is_encrypted:
                raise EncryptedPdfError(f"Encrypted PDF is not supported: {path}") from exc
            raise InvalidPdfError(f"Failed to read pages from PDF: {path}") from exc

        start = min(self.start_page, page_count + 1)
        end = page_count + 1
        if self.max_pages is not None:
            end = min(end, start + self.max_pages)

        pages: list[PageText] = []
        for idx in range(start, end):
            try:
                page = reader.pages[idx - 1]
                raw_text = page.extract_text() or ""
            except FileNotDecryptedError as exc:
                raise EncryptedPdfError(f"Encrypted PDF is not supported: {path}") from exc
            except PdfReadError as exc:
                if reader.is_encrypted:
                    raise EncryptedPdfError(
                        f"Encrypted PDF is not supported: {path}"
                    ) from exc
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
            page_count=page_count,
            pages=pages,
        )
