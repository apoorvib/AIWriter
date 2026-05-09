from __future__ import annotations

from essay_writer.sources.schema import SourcePage
from essay_writer.sources.text_quality import is_better_extraction, text_signal_score


def _page(text: str, page_number: int = 1, method: str = "pypdf") -> SourcePage:
    return SourcePage(
        source_id="src1",
        page_number=page_number,
        text=text,
        char_count=len(text),
        extraction_method=method,
    )


def test_text_signal_score_separates_clean_prose_from_ocr_noise() -> None:
    clean = (
        "The committee evaluated the proposal during the spring semester and "
        "concluded that the framework should be revised before the next review."
    )
    ocr_garbage = "kqxz pwlmxz tt nn b cc rr 1l1l 0o0o ii ;;;:: -- '' qpwx"

    assert text_signal_score(clean) > 0.7
    assert text_signal_score(ocr_garbage) < 0.4
    assert text_signal_score(clean) > text_signal_score(ocr_garbage)


def test_text_signal_score_handles_empty_input() -> None:
    assert text_signal_score("") == 0.0
    assert text_signal_score("   \n\n\t   ") == 0.0


def test_longer_but_noisier_ocr_does_not_replace_clean_text() -> None:
    """Q8: this is the failure mode the bug entry called out — OCR returns
    more characters than the text-layer extraction, but most of those extra
    chars are garbage. Bare char_count comparison would silently overwrite
    correct prose with noise."""
    clean = _page(
        "The framework requires three steps. First, identify the constraint. "
        "Second, propose a revision. Third, validate against the rubric.",
        method="pypdf",
    )
    noisy_ocr = _page(
        clean.text + " kqxz pwlmxz ttnnbccrr 1l1l 0o0o ;;;::: --- ''' qpwx zz xx",
        method="ocr:tesseract",
    )

    assert noisy_ocr.char_count > clean.char_count
    assert is_better_extraction(noisy_ocr, clean) is False


def test_clearly_higher_signal_ocr_replaces_garbled_text() -> None:
    """The opposite case: text-layer extraction failed (returned ligature
    garbage), OCR recovered real prose. Replacement should happen."""
    garbled = _page("ﬁ ﬁ ﬂ ﬃ // /// ::::::::: \\\\\\", method="pypdf")
    recovered = _page(
        "The introduction frames the question and surveys the prior literature "
        "before the methods section begins.",
        method="ocr:tesseract",
    )

    assert is_better_extraction(recovered, garbled) is True


def test_empty_candidate_never_wins() -> None:
    current = _page("Some real text body present here.")
    assert is_better_extraction(_page(""), current) is False
    assert is_better_extraction(_page("   \n\t  "), current) is False


def test_non_empty_candidate_wins_when_current_missing_or_empty() -> None:
    candidate = _page("Recovered prose from OCR pass.")
    assert is_better_extraction(candidate, None) is True
    assert is_better_extraction(candidate, _page("")) is True


def test_equal_score_falls_back_to_length() -> None:
    base = "the cat sat on the rug. the dog ate the food. the bird flew home."
    short = _page(base)
    longer_same_quality = _page(base + " " + base)
    assert is_better_extraction(longer_same_quality, short) is True
    assert is_better_extraction(short, longer_same_quality) is False
