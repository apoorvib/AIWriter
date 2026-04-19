from __future__ import annotations

from pdf_pipeline.cli import _build_parser


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
