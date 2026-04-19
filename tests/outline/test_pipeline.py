from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pypdf import PdfWriter

from llm.mock import MockLLMClient
from pdf_pipeline.outline.pipeline import extract_outline
from pdf_pipeline.outline.schema import DocumentOutline


def _build_pdf_with_outline(tmp_path: Path, outline: list[tuple[str, int]]) -> Path:
    writer = PdfWriter()
    max_page = max((p for _, p in outline), default=1)
    for _ in range(max_page):
        writer.add_blank_page(width=612, height=792)
    for title, page in outline:
        writer.add_outline_item(title, page - 1)
    path = tmp_path / "x.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_uses_pdf_outline_when_present(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [("Chapter 1", 5), ("Chapter 2", 20), ("Chapter 3", 50)],
    )
    client = MockLLMClient(responses=[])  # must not be called

    outline = extract_outline(str(pdf), llm_client=client, source_id="s1")

    assert isinstance(outline, DocumentOutline)
    assert outline.source_id == "s1"
    assert outline.version == 1
    assert len(outline.entries) == 3
    assert [e.title for e in outline.entries] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert [e.start_pdf_page for e in outline.entries] == [5, 20, 50]
    assert all(e.source == "pdf_outline" for e in outline.entries)
    assert [e.end_pdf_page for e in outline.entries] == [19, 49, 50]
    assert client.calls == []


def test_falls_back_to_llm_when_no_outline(tmp_path: Path, monkeypatch):
    # Plain PDF with no bookmarks, no page labels.
    writer = PdfWriter()
    for _ in range(20):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "plain.pdf"
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    # Stub the page text source so the orchestrator sees TOC-looking text on
    # page 3 and body text matching the TOC titles on later pages.
    fake_pages = {
        1: "front matter",
        2: "dedication",
        3: "Contents\n\nChapter 1: Origins ........ 1\nChapter 2: Methods ........ 10\n",
        4: "further TOC\nChapter 3: Results ....... 15",
        5: "\n\nChapter 1: Origins\n\nbody starts here",
        14: "\n\nChapter 2: Methods\n\nbody",
        19: "\n\nChapter 3: Results\n\nbody",
    }
    from pdf_pipeline.outline import pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod, "_load_pages_text", lambda pdf_path_, total_pages, max_pages, **_: fake_pages
    )

    client = MockLLMClient(
        responses=[
            # chunk 1: pages 1..5 - TOC entries extracted
            {
                "pages": [{"pdf_page": p, "is_toc": (p in (3, 4))} for p in range(1, 6)],
                "entries": [
                    {"title": "Chapter 1: Origins", "level": 1, "printed_page": "1"},
                    {"title": "Chapter 2: Methods", "level": 1, "printed_page": "10"},
                    {"title": "Chapter 3: Results", "level": 1, "printed_page": "15"},
                ],
            },
            # chunk 2: pages 6..10 - no TOC -> stop
            {
                "pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)],
                "entries": [],
            },
        ]
    )

    outline = extract_outline(str(pdf_path), llm_client=client, source_id="s2", max_toc_pages=10, chunk_size=5)
    assert len(outline.entries) == 3
    assert all(e.source == "anchor_scan" for e in outline.entries)
    assert [e.start_pdf_page for e in outline.entries] == [5, 14, 19]


def test_uses_page_labels_when_present(tmp_path: Path, monkeypatch):
    # Plain PDF with no bookmarks; stub /PageLabels via monkeypatch.
    writer = PdfWriter()
    for _ in range(20):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "labeled.pdf"
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    fake_pages = {
        1: "front",
        2: "dedication",
        3: "Contents\n\nChapter 1 ........ 1\nChapter 2 ........ 10\n",
    }
    from pdf_pipeline.outline import pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod, "_load_pages_text", lambda p_, total_pages, max_pages, **_: fake_pages
    )
    # Printed "1" -> pdf_page 5; printed "10" -> pdf_page 14.
    labels = {i: str(i - 4) for i in range(5, 21)}
    monkeypatch.setattr(pipeline_mod, "read_page_labels", lambda _p: labels)

    client = MockLLMClient(
        responses=[
            {
                "pages": [{"pdf_page": p, "is_toc": (p == 3)} for p in range(1, 6)],
                "entries": [
                    {"title": "Chapter 1", "level": 1, "printed_page": "1"},
                    {"title": "Chapter 2", "level": 1, "printed_page": "10"},
                ],
            },
            {
                "pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)],
                "entries": [],
            },
        ]
    )

    outline = extract_outline(
        str(pdf_path), llm_client=client, source_id="s4", max_toc_pages=10, chunk_size=5
    )
    assert len(outline.entries) == 2
    assert all(e.source == "page_labels" for e in outline.entries)
    assert [e.start_pdf_page for e in outline.entries] == [5, 14]


def test_returns_empty_outline_when_no_toc_and_no_metadata(tmp_path: Path, monkeypatch):
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=612, height=792)
    pdf = tmp_path / "plain.pdf"
    with pdf.open("wb") as fh:
        writer.write(fh)

    from pdf_pipeline.outline import pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod, "_load_pages_text",
        lambda pdf_path_, total_pages, max_pages, **_: {i: "narrative body" for i in range(1, 6)},
    )

    client = MockLLMClient(responses=[])  # prefilter should short-circuit; client never called

    outline = extract_outline(str(pdf), llm_client=client, source_id="s3", max_toc_pages=5)
    assert outline.entries == []
    assert client.calls == []


def test_load_pages_text_parallel_calls_run_parallel_ocr(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import pdf_pipeline.ocr_parallel as par_mod
    from pdf_pipeline.models import DocumentExtractionResult, PageText
    from pdf_pipeline.ocr import OcrConfig, OcrTier
    from pdf_pipeline.outline import pipeline as pipeline_mod

    fake_pages = [
        PageText(page_number=i, text=f"text {i}", char_count=6, extraction_method="ocr:small")
        for i in range(1, 4)
    ]
    fake_result = DocumentExtractionResult(source_path="x.pdf", page_count=10, pages=fake_pages)
    fake_summary = MagicMock()
    captured = {}

    def fake_run_parallel_ocr(pdf_path, config):
        captured["config"] = config
        return fake_summary, fake_result

    monkeypatch.setattr(par_mod, "run_parallel_ocr", fake_run_parallel_ocr)

    result = pipeline_mod._load_pages_text(
        "x.pdf",
        total_pages=10,
        max_pages=3,
        ocr_tier=OcrTier.SMALL,
        ocr_config=OcrConfig(languages=("en",), dpi=200),
        parallel_workers=2,
        calibrate=False,
    )

    assert result == {1: "text 1", 2: "text 2", 3: "text 3"}
    cfg = captured["config"]
    assert cfg.max_pages == 3
    assert cfg.workers == 2
    assert cfg.dpi == 200
    assert cfg.languages == ("en",)
    assert cfg.calibrate is False


def test_extract_outline_passes_parallel_params_to_load_pages_text(tmp_path, monkeypatch):
    from pypdf import PdfWriter
    from pdf_pipeline.outline import pipeline as pipeline_mod
    from llm.mock import MockLLMClient

    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "plain.pdf"
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    captured = {}

    def fake_load_pages_text(pdf_path_, total_pages, max_pages, **kwargs):
        captured.update(kwargs)
        return {i: "narrative body text here" for i in range(1, 6)}

    monkeypatch.setattr(pipeline_mod, "_load_pages_text", fake_load_pages_text)

    client = MockLLMClient(responses=[])
    pipeline_mod.extract_outline(
        str(pdf_path),
        llm_client=client,
        source_id="s",
        parallel_workers="auto",
        calibrate=True,
    )

    assert captured.get("parallel_workers") == "auto"
    assert captured.get("calibrate") is True
