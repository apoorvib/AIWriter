from unittest.mock import MagicMock

from pdf_pipeline.outline.page_text import (
    LazyPageTextMap,
    LazyTesseractPageExtractor,
    PageTextRecord,
    PageTextSource,
)
from pdf_pipeline.ocr import OcrTier


def test_uses_text_when_present():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = "hello world"
    ocr_extractor = MagicMock()

    src = PageTextSource(
        text_extractor=text_extractor,
        ocr_extractor=ocr_extractor,
        min_chars=5,
    )
    record = src.get("some.pdf", pdf_page=3)

    assert record == PageTextRecord(pdf_page=3, text="hello world", used_ocr=False)
    ocr_extractor.extract_page_text.assert_not_called()


def test_falls_back_to_ocr_when_text_empty():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = ""
    ocr_extractor = MagicMock()
    ocr_extractor.extract_page_text.return_value = "ocr said hi"

    src = PageTextSource(
        text_extractor=text_extractor,
        ocr_extractor=ocr_extractor,
        min_chars=5,
    )
    record = src.get("some.pdf", pdf_page=7)

    assert record == PageTextRecord(pdf_page=7, text="ocr said hi", used_ocr=True)


def test_falls_back_when_text_is_below_min_chars():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = "x"
    ocr_extractor = MagicMock()
    ocr_extractor.extract_page_text.return_value = "full ocr text here"

    src = PageTextSource(
        text_extractor=text_extractor,
        ocr_extractor=ocr_extractor,
        min_chars=5,
    )
    record = src.get("some.pdf", pdf_page=2)
    assert record.used_ocr is True
    assert record.text == "full ocr text here"


def test_works_without_ocr_extractor_when_text_present():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = "enough text here"

    src = PageTextSource(text_extractor=text_extractor, ocr_extractor=None, min_chars=5)
    record = src.get("some.pdf", pdf_page=1)
    assert record.used_ocr is False
    assert record.text == "enough text here"


def test_returns_empty_record_when_both_fail():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = ""
    ocr_extractor = MagicMock()
    ocr_extractor.extract_page_text.return_value = ""

    src = PageTextSource(text_extractor=text_extractor, ocr_extractor=ocr_extractor, min_chars=5)
    record = src.get("some.pdf", pdf_page=1)
    assert record == PageTextRecord(pdf_page=1, text="", used_ocr=True)


def _fake_source(texts: dict[int, str]) -> PageTextSource:
    src = MagicMock(spec=PageTextSource)
    src.get.side_effect = lambda path, page: PageTextRecord(
        pdf_page=page, text=texts.get(page, ""), used_ocr=False
    )
    return src


def test_lazy_map_fetches_on_demand_and_caches():
    src = _fake_source({5: "page five", 14: "page fourteen"})
    m = LazyPageTextMap(src, "x.pdf", total_pages=100)

    assert m.cached_count == 0
    assert m.get(5) == "page five"
    assert m.get(5) == "page five"  # cached, second call shouldn't re-fetch
    assert m.get(14) == "page fourteen"

    assert src.get.call_count == 2
    assert m.cached_count == 2


def test_lazy_map_out_of_range_returns_default_without_fetch():
    src = _fake_source({})
    m = LazyPageTextMap(src, "x.pdf", total_pages=10)

    assert m.get(0) == ""
    assert m.get(11) == ""
    assert m.get(11, default="missing") == "missing"
    src.get.assert_not_called()


def test_lazy_map_mapping_protocol():
    src = _fake_source({1: "a", 3: "c"})
    m = LazyPageTextMap(src, "x.pdf", total_pages=5)

    assert len(m) == 5
    assert list(m.keys()) == [1, 2, 3, 4, 5]
    assert 3 in m
    assert 99 not in m
    assert "bogus" not in m  # non-int contains returns False
    assert m[1] == "a"


def test_lazy_map_getitem_out_of_range_raises():
    src = _fake_source({})
    m = LazyPageTextMap(src, "x.pdf", total_pages=5)
    try:
        _ = m[0]
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
    try:
        _ = m[6]
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_small_ocr_outline_fallback_uses_lazy_tesseract_extractor():
    from pdf_pipeline.outline.pipeline import _build_ocr_page_extractor

    extractor = _build_ocr_page_extractor(OcrTier.SMALL, ocr_config=None)

    assert isinstance(extractor, LazyTesseractPageExtractor)
