from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf_pipeline.extractors.base import InvalidPdfError, MissingDependencyError


def rasterize_pdf_pages(pdf_path: str | Path, dpi: int) -> list[Any]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise MissingDependencyError(
            "Missing optional dependency 'pypdfium2'. Install an OCR extra to enable rasterization."
        ) from exc

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {path.suffix}")

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:  # pragma: no cover - backend-specific failure mode
        raise InvalidPdfError(f"Could not read PDF: {path}") from exc

    scale = dpi / 72.0
    images: list[Any] = []
    for page in pdf:
        pil_image = page.render(scale=scale).to_pil()
        images.append(pil_image)
    return images
