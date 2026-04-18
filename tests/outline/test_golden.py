from pathlib import Path

from llm.mock import MockLLMClient
from pdf_pipeline.outline import extract_outline


FIXTURES = Path(__file__).parent / "fixtures"


def test_born_digital_with_outlines_uses_layer_1():
    """PDF with /Outlines should not call the LLM."""
    client = MockLLMClient(responses=[])
    outline = extract_outline(
        str(FIXTURES / "born_digital_with_outlines.pdf"),
        llm_client=client,
        source_id="golden-1",
    )
    assert [e.title for e in outline.entries] == [
        "Chapter 1: Origins",
        "Chapter 2: Methods",
        "Chapter 3: Results",
    ]
    assert [e.start_pdf_page for e in outline.entries] == [5, 15, 25]
    assert [e.end_pdf_page for e in outline.entries] == [14, 24, 30]
    assert all(e.source == "pdf_outline" for e in outline.entries)
    assert client.calls == []


def test_article_no_toc_returns_empty_outline():
    """Article with no outline and no TOC should produce an empty outline."""
    client = MockLLMClient(responses=[])
    outline = extract_outline(
        str(FIXTURES / "article_no_toc.pdf"),
        llm_client=client,
        source_id="golden-2",
    )
    assert outline.entries == []
    assert client.calls == []  # prefilter short-circuited
