from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig, OcrTier
from pdf_pipeline.ocr_parallel import ParallelOcrConfig, run_parallel_ocr
from pdf_pipeline.pipeline import ExtractionPipeline

load_dotenv()


def _cmd_extract(args: argparse.Namespace) -> int:
    pipeline = ExtractionPipeline(
        mode=ExtractionMode(args.mode),
        ocr_tier=OcrTier(args.ocr_tier),
        ocr_config=OcrConfig(
            languages=tuple(args.ocr_lang),
            dpi=args.ocr_dpi,
            use_gpu=args.ocr_gpu,
            start_page=args.start_page,
            max_pages=args.max_pages,
        ),
    )
    result = pipeline.extract(args.pdf_path)
    print(
        json.dumps(
            {
                "source_path": result.source_path,
                "page_count": result.page_count,
                "pages": [page.__dict__ for page in result.pages],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


def _cmd_outline(args: argparse.Namespace) -> int:
    from llm.factory import make_client
    from pdf_pipeline.outline import OutlineStore, extract_outline

    client = make_client(args.provider)
    store = OutlineStore(root=args.store)
    tier = OcrTier(args.ocr_tier) if args.ocr_tier else None
    config = OcrConfig(
        languages=tuple(args.ocr_lang),
        dpi=args.ocr_dpi,
        use_gpu=args.ocr_gpu,
    )
    outline = extract_outline(
        args.pdf_path,
        llm_client=client,
        source_id=args.source_id,
        ocr_tier=tier,
        ocr_config=config,
        llm_model=args.llm_model,
    )
    store.save(outline)
    for entry in outline.entries:
        print(
            f"[{entry.source}] lvl {entry.level} "
            f"pdf_page={entry.start_pdf_page}-{entry.end_pdf_page} "
            f"printed={entry.printed_page} "
            f"conf={entry.confidence:.2f}  {entry.title}"
        )
    return 0


def _cmd_ocr_parallel(args: argparse.Namespace) -> int:
    config = ParallelOcrConfig(
        ocr_tier=OcrTier(args.ocr_tier),
        languages=tuple(args.ocr_lang),
        dpi=args.ocr_dpi,
        use_gpu=args.ocr_gpu,
        start_page=args.start_page,
        max_pages=args.max_pages,
        workers=args.workers,
        calibrate=args.calibrate,
        max_attempts=args.max_attempts,
        timeout_seconds=args.timeout_seconds,
        store_path=args.store,
        document_id=args.document_id,
        shared_machine=args.shared_machine,
        omp_thread_limit=args.omp_thread_limit,
        resume=args.resume,
    )
    summary, result = run_parallel_ocr(args.pdf_path, config=config)
    if args.json_summary:
        print(json.dumps(_json_ready(asdict(summary)), ensure_ascii=True, indent=2))
    else:
        print(
            json.dumps(
                {
                    "source_path": result.source_path,
                    "page_count": result.page_count,
                    "pages": [page.__dict__ for page in result.pages],
                    "ocr_summary": _json_ready(asdict(summary)),
                },
                ensure_ascii=True,
                indent=2,
            )
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF extraction and outline tools.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Enable logging (-v for INFO, -vv for DEBUG).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract", help="Extract text from a text-native PDF.")
    extract_parser.add_argument("pdf_path", help="Path to input PDF")
    extract_parser.add_argument(
        "--mode",
        choices=[m.value for m in ExtractionMode],
        default=ExtractionMode.TEXT_ONLY.value,
        help="Extraction mode: text_only, ocr_only, auto",
    )
    extract_parser.add_argument(
        "--ocr-tier",
        choices=[t.value for t in OcrTier],
        default=OcrTier.SMALL.value,
        help="OCR model tier to use when mode is ocr_only.",
    )
    extract_parser.add_argument(
        "--ocr-dpi",
        type=int,
        default=300,
        help="Rasterization DPI for OCR modes.",
    )
    extract_parser.add_argument(
        "--ocr-lang",
        action="append",
        default=["en"],
        help="OCR language code (repeatable). Example: --ocr-lang en --ocr-lang fr",
    )
    extract_parser.add_argument(
        "--ocr-gpu",
        action="store_true",
        help="Enable GPU usage for supported OCR backends.",
    )
    extract_parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First PDF page to process in OCR modes.",
    )
    extract_parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of pages to process in OCR modes.",
    )
    extract_parser.set_defaults(func=_cmd_extract)

    parallel_parser = subparsers.add_parser(
        "ocr-parallel",
        help="Run page-level parallel OCR for a PDF.",
    )
    parallel_parser.add_argument("pdf_path", help="Path to input PDF")
    parallel_parser.add_argument(
        "--ocr-tier",
        choices=[t.value for t in OcrTier],
        default=OcrTier.SMALL.value,
        help="OCR model tier. Parallel execution currently supports small/Tesseract.",
    )
    parallel_parser.add_argument(
        "--ocr-dpi",
        type=int,
        default=300,
        help="Rasterization DPI for OCR.",
    )
    parallel_parser.add_argument(
        "--ocr-lang",
        action="append",
        default=["en"],
        help="OCR language code (repeatable). Example: --ocr-lang en --ocr-lang fr",
    )
    parallel_parser.add_argument(
        "--ocr-gpu",
        action="store_true",
        help="Reserved for GPU OCR backends; ignored for Tesseract.",
    )
    parallel_parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First PDF page to process.",
    )
    parallel_parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of pages to process.",
    )
    parallel_parser.add_argument(
        "--workers",
        default="auto",
        help="Worker count or 'auto'.",
    )
    parallel_parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Benchmark sample pages and select a measured worker count when --workers is auto.",
    )
    parallel_parser.add_argument(
        "--store",
        default="./ocr_store",
        help="OCR artifact store root.",
    )
    parallel_parser.add_argument(
        "--document-id",
        default=None,
        help="Optional stable document id for artifact storage.",
    )
    parallel_parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Maximum attempts per page.",
    )
    parallel_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Reserved for future per-page timeout support.",
    )
    parallel_parser.add_argument(
        "--json-summary",
        action="store_true",
        help="Print only run summary JSON instead of merged page text.",
    )
    parallel_parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing successful page artifacts for this document id.",
    )
    parallel_parser.add_argument(
        "--shared-machine",
        action="store_true",
        default=None,
        help="Use conservative worker planning for an interactive/shared machine.",
    )
    parallel_parser.add_argument(
        "--dedicated-machine",
        action="store_false",
        dest="shared_machine",
        help="Use more aggressive worker planning for a dedicated OCR machine.",
    )
    parallel_parser.add_argument(
        "--omp-thread-limit",
        type=int,
        default=None,
        help="OpenMP thread limit for Tesseract workers. Defaults to 1.",
    )
    parallel_parser.set_defaults(func=_cmd_ocr_parallel)

    outline_parser = subparsers.add_parser("outline", help="Extract a document outline")
    outline_parser.add_argument("pdf_path", help="Path to PDF")
    outline_parser.add_argument("--source-id", required=True)
    outline_parser.add_argument("--provider", default=None, help="LLM provider (claude/openai/gemini)")
    outline_parser.add_argument(
        "--llm-model",
        default=None,
        dest="llm_model",
        metavar="MODEL",
        help="Model id for this run (overrides the client default for each LLM call).",
    )
    outline_parser.add_argument("--store", default="./outline_store", help="Storage root")
    outline_parser.add_argument(
        "--ocr-tier",
        choices=[t.value for t in OcrTier],
        default=None,
        help="Enable OCR fallback for pages where pypdf returns no text (small/medium/high).",
    )
    outline_parser.add_argument(
        "--ocr-dpi", type=int, default=300, help="Rasterization DPI for OCR."
    )
    outline_parser.add_argument(
        "--ocr-lang",
        action="append",
        default=["en"],
        help="OCR language code (repeatable).",
    )
    outline_parser.add_argument(
        "--ocr-gpu", action="store_true", help="Enable GPU for supported OCR backends."
    )
    outline_parser.set_defaults(func=_cmd_outline)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return args.func(args)


def _json_ready(value):
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
