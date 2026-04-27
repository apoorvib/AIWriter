from essay_writer.writing_style.normalizer import normalize_writing_sample_text


def test_normalizer_joins_wrapped_lines_into_paragraphs() -> None:
    raw = "A Time Series is a series of discrete-time data that is\narranged chronologically."
    normalized = normalize_writing_sample_text(raw)
    assert normalized.text == "A Time Series is a series of discrete-time data that is arranged chronologically."


def test_normalizer_heals_simple_linebreak_hyphenation() -> None:
    raw = "This gives the full representa-\ntion of the fields."
    normalized = normalize_writing_sample_text(raw)
    assert normalized.text == "This gives the full representation of the fields."


def test_normalizer_preserves_non_wordbreak_hyphen_runs() -> None:
    raw = "The planet Kepler-\n1625b may host a moon."
    normalized = normalize_writing_sample_text(raw)
    assert normalized.text == "The planet Kepler-1625b may host a moon."


def test_normalizer_repairs_common_utf8_mojibake() -> None:
    raw = "Earth\u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u201e\u00a2s moon stabilizes the planet."
    normalized = normalize_writing_sample_text(raw)
    assert normalized.text == "Earth\u2019s moon stabilizes the planet."
