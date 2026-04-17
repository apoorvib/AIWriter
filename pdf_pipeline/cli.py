from __future__ import annotations

import argparse
import json

from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig, OcrTier
from pdf_pipeline.pipeline import ExtractionPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a text-native PDF.")
    parser.add_argument("pdf_path", help="Path to input PDF")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ExtractionMode],
        default=ExtractionMode.TEXT_ONLY.value,
        help="Extraction mode: text_only, ocr_only, auto",
    )
    parser.add_argument(
        "--ocr-tier",
        choices=[t.value for t in OcrTier],
        default=OcrTier.SMALL.value,
        help="OCR model tier to use when mode is ocr_only.",
    )
    parser.add_argument(
        "--ocr-dpi",
        type=int,
        default=300,
        help="Rasterization DPI for OCR modes.",
    )
    parser.add_argument(
        "--ocr-lang",
        action="append",
        default=["en"],
        help="OCR language code (repeatable). Example: --ocr-lang en --ocr-lang fr",
    )
    parser.add_argument(
        "--ocr-gpu",
        action="store_true",
        help="Enable GPU usage for supported OCR backends.",
    )
    args = parser.parse_args()
    pipeline = ExtractionPipeline(
        mode=ExtractionMode(args.mode),
        ocr_tier=OcrTier(args.ocr_tier),
        ocr_config=OcrConfig(languages=tuple(args.ocr_lang), dpi=args.ocr_dpi, use_gpu=args.ocr_gpu),
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


if __name__ == "__main__":
    main()
