from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from pdf_pipeline.extractors import MissingDependencyError
from pdf_pipeline.extractors.easyocr_extractor import EasyOcrExtractor
from pdf_pipeline.extractors.paddle_extractor import PaddleOcrExtractor
from pdf_pipeline.extractors.tesseract_extractor import TesseractOcrExtractor
from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.pipeline import ExtractionPipeline


def test_auto_mode_raises_not_implemented() -> None:
    pipeline = ExtractionPipeline(mode=ExtractionMode.AUTO)
    with pytest.raises(NotImplementedError):
        pipeline.extract("dummy.pdf")


def test_tesseract_extractor_reports_missing_dependency() -> None:
    extractor = TesseractOcrExtractor()
    with pytest.raises((FileNotFoundError, MissingDependencyError)):
        extractor.extract("dummy.pdf")


def test_easyocr_extractor_reports_missing_dependency() -> None:
    extractor = EasyOcrExtractor()
    with pytest.raises(MissingDependencyError):
        extractor.extract("dummy.pdf")


def test_paddle_extractor_reports_missing_dependency() -> None:
    extractor = PaddleOcrExtractor()
    with pytest.raises(MissingDependencyError):
        extractor.extract("dummy.pdf")


def test_pipeline_routes_ocr_tier_selection() -> None:
    assert ExtractionPipeline(mode=ExtractionMode.OCR_ONLY, ocr_tier=OcrTier.SMALL)._resolve_extractor().__class__.__name__ == "TesseractOcrExtractor"  # noqa: SLF001
    assert ExtractionPipeline(mode=ExtractionMode.OCR_ONLY, ocr_tier=OcrTier.MEDIUM)._resolve_extractor().__class__.__name__ == "EasyOcrExtractor"  # noqa: SLF001
    assert ExtractionPipeline(mode=ExtractionMode.OCR_ONLY, ocr_tier=OcrTier.HIGH)._resolve_extractor().__class__.__name__ == "PaddleOcrExtractor"  # noqa: SLF001


def test_easyocr_backend_with_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_pipeline.extractors.easyocr_extractor as module

    class DummyReader:
        def __init__(self, langs: list[str], gpu: bool) -> None:
            self.langs = langs
            self.gpu = gpu

        def readtext(self, _array, detail: int, paragraph: bool) -> list[str]:
            assert detail == 0
            assert paragraph is True
            return ["hello", "world"]

    monkeypatch.setattr(module, "iter_rasterized_pdf_pages", lambda _path, dpi, start_page, max_pages: [(1, object())])
    monkeypatch.setitem(__import__("sys").modules, "easyocr", SimpleNamespace(Reader=DummyReader))
    monkeypatch.setitem(__import__("sys").modules, "numpy", SimpleNamespace(array=lambda x: x))

    result = module.EasyOcrExtractor().extract("fake.pdf")
    assert result.page_count == 1
    assert result.pages[0].text == "hello\nworld"
    assert result.pages[0].extraction_method == "ocr:easyocr"


def test_tesseract_backend_with_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_pipeline.extractors.tesseract_extractor as module

    monkeypatch.setattr(module, "iter_rasterized_pdf_pages", lambda _path, dpi, start_page, max_pages: [(1, object()), (2, object())])
    def image_to_string(_image, lang: str) -> str:
        assert lang == "eng"
        return f"text-{lang}"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", SimpleNamespace(image_to_string=image_to_string))

    result = module.TesseractOcrExtractor().extract("fake.pdf")
    assert result.page_count == 2
    assert result.pages[0].text.startswith("text-")
    assert result.pages[0].extraction_method == "ocr:tesseract"


def test_paddle_backend_with_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_pipeline.extractors.paddle_extractor as module

    class DummyPaddleOCR:
        def __init__(self, lang: str, use_gpu: bool, ocr_version: str) -> None:
            self.lang = lang
            self.use_gpu = use_gpu
            self.ocr_version = ocr_version

        def ocr(self, _array, cls: bool) -> list:
            assert cls is True
            return [[[None, ("paddle text", 0.98)]]]

    monkeypatch.setattr(module, "iter_rasterized_pdf_pages", lambda _path, dpi, start_page, max_pages: [(1, object())])
    monkeypatch.setitem(__import__("sys").modules, "paddleocr", SimpleNamespace(PaddleOCR=DummyPaddleOCR))
    monkeypatch.setitem(__import__("sys").modules, "numpy", SimpleNamespace(array=lambda x: x))

    result = module.PaddleOcrExtractor().extract("fake.pdf")
    assert result.page_count == 1
    assert result.pages[0].text == "paddle text"
    assert result.pages[0].extraction_method == "ocr:paddleocr"


@pytest.mark.skipif(importlib.util.find_spec("pypdfium2") is None, reason="pypdfium2 not installed")
def test_optional_smoke_rasterization_api_shape(tmp_path) -> None:
    # Optional smoke coverage that only asserts import/runtime shape when OCR rasterization dependency exists.
    from pypdf import PdfWriter

    from pdf_pipeline.extractors.ocr_common import rasterize_pdf_pages

    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    images = rasterize_pdf_pages(pdf_path, dpi=72)
    assert len(images) == 1
