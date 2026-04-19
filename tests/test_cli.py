from __future__ import annotations

import sys

from pdf_pipeline.cli import _build_parser, _configure_utf8_stdio


class _FakeStream:
    def __init__(self) -> None:
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_outline_parallel_workers_and_calibrate_parsed():
    parser = _build_parser()
    args = parser.parse_args([
        "outline", "doc.pdf",
        "--source-id", "my-doc",
        "--ocr-tier", "small",
        "--parallel-workers", "auto",
        "--calibrate",
    ])
    assert args.parallel_workers == "auto"
    assert args.calibrate is True


def test_outline_parallel_workers_integer_string():
    parser = _build_parser()
    args = parser.parse_args([
        "outline", "doc.pdf",
        "--source-id", "my-doc",
        "--parallel-workers", "4",
    ])
    assert args.parallel_workers == "4"
    assert args.calibrate is False


def test_outline_parallel_workers_defaults_to_none():
    parser = _build_parser()
    args = parser.parse_args(["outline", "doc.pdf", "--source-id", "my-doc"])
    assert args.parallel_workers is None
    assert args.calibrate is False


def test_outline_toc_extraction_mode_parsed():
    parser = _build_parser()
    args = parser.parse_args([
        "outline", "doc.pdf",
        "--source-id", "my-doc",
        "--toc-extraction-mode", "deterministic",
        "--deterministic-min-toc-entries", "25",
    ])
    assert args.toc_extraction_mode == "deterministic"
    assert args.deterministic_min_toc_entries == 25


def test_outline_toc_extraction_mode_defaults():
    parser = _build_parser()
    args = parser.parse_args(["outline", "doc.pdf", "--source-id", "my-doc"])
    assert args.toc_extraction_mode == "auto"
    assert args.deterministic_min_toc_entries == 10


def test_configure_utf8_stdio_reconfigures_stdout_and_stderr(monkeypatch):
    stdout = _FakeStream()
    stderr = _FakeStream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    _configure_utf8_stdio()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]
