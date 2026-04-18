from __future__ import annotations

import argparse
import json
import logging
from typing import Sequence

from dotenv import load_dotenv

from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig, OcrTier
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
    outline = extract_outline(args.pdf_path, llm_client=client, source_id=args.source_id)
    store.save(outline)
    for entry in outline.entries:
        print(
            f"[{entry.source}] lvl {entry.level} "
            f"pdf_page={entry.start_pdf_page}-{entry.end_pdf_page} "
            f"printed={entry.printed_page} "
            f"conf={entry.confidence:.2f}  {entry.title}"
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
    extract_parser.set_defaults(func=_cmd_extract)

    outline_parser = subparsers.add_parser("outline", help="Extract a document outline")
    outline_parser.add_argument("pdf_path", help="Path to PDF")
    outline_parser.add_argument("--source-id", required=True)
    outline_parser.add_argument("--provider", default=None, help="LLM provider (claude/openai/gemini)")
    outline_parser.add_argument("--store", default="./outline_store", help="Storage root")
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


if __name__ == "__main__":
    raise SystemExit(main())
