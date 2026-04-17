from __future__ import annotations

from pdf_pipeline.outline.entry_extraction import RawEntry, extract_toc_entries
from llm.mock import MockLLMClient


def _pages(start: int, count: int, text: str = "body") -> list[dict]:
    return [{"pdf_page": start + i, "text": text} for i in range(count)]


def test_chunk_math_ceil():
    responses = [
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(1, 6)], "entries": []},
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)], "entries": []},
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(11, 14)], "entries": []},
    ]
    client = MockLLMClient(responses=responses)

    pages = _pages(1, 13)
    entries = extract_toc_entries(pages, client, chunk_size=5)

    assert entries == []
    assert len(client.calls) == 3


def test_stops_after_toc_block_ends():
    responses = [
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(1, 6)], "entries": []},
        {
            "pages": [
                {"pdf_page": 6, "is_toc": True},
                {"pdf_page": 7, "is_toc": True},
                {"pdf_page": 8, "is_toc": False},
                {"pdf_page": 9, "is_toc": False},
                {"pdf_page": 10, "is_toc": False},
            ],
            "entries": [
                {"title": "Chapter 1: Origins", "level": 1, "printed_page": "1"},
                {"title": "Chapter 2: Methods", "level": 1, "printed_page": "15"},
            ],
        },
    ]
    client = MockLLMClient(responses=responses)

    pages = _pages(1, 15)
    entries = extract_toc_entries(pages, client, chunk_size=5)

    assert len(entries) == 2
    assert entries[0] == RawEntry(title="Chapter 1: Origins", level=1, printed_page="1")
    assert len(client.calls) == 2


def test_spans_chunk_boundary():
    responses = [
        {
            "pages": [
                {"pdf_page": 1, "is_toc": False},
                {"pdf_page": 2, "is_toc": False},
                {"pdf_page": 3, "is_toc": True},
                {"pdf_page": 4, "is_toc": True},
                {"pdf_page": 5, "is_toc": True},
            ],
            "entries": [
                {"title": "Preface", "level": 1, "printed_page": "ix"},
                {"title": "Ch 1", "level": 1, "printed_page": "1"},
            ],
        },
        {
            "pages": [
                {"pdf_page": 6, "is_toc": True},
                {"pdf_page": 7, "is_toc": False},
                {"pdf_page": 8, "is_toc": False},
                {"pdf_page": 9, "is_toc": False},
                {"pdf_page": 10, "is_toc": False},
            ],
            "entries": [
                {"title": "Ch 2", "level": 1, "printed_page": "25"},
            ],
        },
    ]
    client = MockLLMClient(responses=responses)
    entries = extract_toc_entries(_pages(1, 10), client, chunk_size=5)

    titles = [e.title for e in entries]
    assert titles == ["Preface", "Ch 1", "Ch 2"]


def test_returns_empty_when_no_toc_ever_seen():
    responses = [
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(1, 6)], "entries": []},
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)], "entries": []},
    ]
    client = MockLLMClient(responses=responses)
    entries = extract_toc_entries(_pages(1, 10), client, chunk_size=5)
    assert entries == []
