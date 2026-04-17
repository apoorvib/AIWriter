from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pdf_pipeline.models import DocumentExtractionResult


class ExtractionError(Exception):
    """Base exception for document extraction errors."""


class InvalidPdfError(ExtractionError):
    """Raised when PDF is unreadable or malformed."""


class InvalidWordDocumentError(ExtractionError):
    """Raised when a Word document is unreadable or malformed."""


class EncryptedPdfError(ExtractionError):
    """Raised when encrypted PDFs are not supported for extraction."""


class MissingDependencyError(ExtractionError):
    """Raised when an optional extraction dependency is unavailable."""


class OcrRuntimeError(ExtractionError):
    """Raised when OCR execution fails at runtime."""


class DocumentExtractor(ABC):
    @abstractmethod
    def extract(self, document_path: str | Path) -> DocumentExtractionResult:
        """Extract text from a document file path."""


class PdfExtractor(DocumentExtractor):
    """Marker base class for PDF extraction implementations."""
