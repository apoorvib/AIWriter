from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from pdf_pipeline.extractors.base import InvalidPdfError, MissingDependencyError


def rasterize_pdf_pages(pdf_path: str | Path, dpi: int) -> list[Any]:
    return [
        image
        for _, image in iter_rasterized_pdf_pages(
            pdf_path,
            dpi=dpi,
            start_page=1,
            max_pages=None,
        )
    ]


def iter_rasterized_pdf_pages(
    pdf_path: str | Path,
    dpi: int,
    start_page: int = 1,
    max_pages: int | None = None,
) -> Iterator[tuple[int, Any]]:
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
    if start_page < 1:
        raise ValueError(f"start_page must be >= 1, got: {start_page}")
    if max_pages is not None and max_pages < 1:
        raise ValueError(f"max_pages must be >= 1, got: {max_pages}")

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:  # pragma: no cover - backend-specific failure mode
        raise InvalidPdfError(f"Could not read PDF: {path}") from exc

    scale = dpi / 72.0
    start_index = start_page - 1
    end_index = len(pdf)
    if max_pages is not None:
        end_index = min(end_index, start_index + max_pages)

    for index in range(start_index, end_index):
        page = pdf[index]
        yield index + 1, page.render(scale=scale).to_pil()
