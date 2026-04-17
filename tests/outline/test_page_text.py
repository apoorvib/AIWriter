from unittest.mock import MagicMock

from pdf_pipeline.outline.page_text import PageTextSource, PageTextRecord


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
