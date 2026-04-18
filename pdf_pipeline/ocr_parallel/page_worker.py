from __future__ import annotations

import os
from time import perf_counter

from pdf_pipeline.extractors.ocr_common import render_pdf_page
from pdf_pipeline.extractors.tesseract_extractor import (
    normalize_tesseract_languages,
    tesseract_image_to_string,
)
from pdf_pipeline.models import PageText
from pdf_pipeline.ocr import OcrTier
from pdf_pipeline.ocr_parallel.schema import OcrPageResult, OcrPageTask
from pdf_pipeline.text_utils import normalize_text


def run_page_ocr_task(task: OcrPageTask) -> OcrPageResult:
    if task.ocr_tier != OcrTier.SMALL:
        return _failed_result(task, f"parallel page OCR is not implemented for tier {task.ocr_tier.value}")

    rasterization_ms = 0.0
    ocr_ms = 0.0
    normalization_ms = 0.0
    try:
        start = perf_counter()
        image = render_pdf_page(task.source_path, task.page_number, task.dpi)
        rasterization_ms = _elapsed_ms(start)

        lang = normalize_tesseract_languages(task.languages)
        start = perf_counter()
        raw_text = tesseract_image_to_string(image, lang=lang)
        ocr_ms = _elapsed_ms(start)

        start = perf_counter()
        text = normalize_text(raw_text or "")
        normalization_ms = _elapsed_ms(start)

        return OcrPageResult(
            document_id=task.document_id,
            source_path=task.source_path,
            page_number=task.page_number,
            text=text,
            char_count=len(text),
            extraction_method="ocr:tesseract",
            rasterization_ms=rasterization_ms,
            ocr_ms=ocr_ms,
            normalization_ms=normalization_ms,
            worker_pid=os.getpid(),
            attempt=task.attempt,
        )
    except Exception as exc:  # pragma: no cover - backend/runtime-specific
        return OcrPageResult(
            document_id=task.document_id,
            source_path=task.source_path,
            page_number=task.page_number,
            text="",
            char_count=0,
            extraction_method="ocr:tesseract",
            rasterization_ms=rasterization_ms,
            ocr_ms=ocr_ms,
            normalization_ms=normalization_ms,
            worker_pid=os.getpid(),
            attempt=task.attempt,
            error_message=str(exc),
        )


def page_result_to_page_text(result: OcrPageResult) -> PageText:
    return PageText(
        page_number=result.page_number,
        text=result.text,
        char_count=result.char_count,
        extraction_method=result.extraction_method,
    )


def _failed_result(task: OcrPageTask, message: str) -> OcrPageResult:
    return OcrPageResult(
        document_id=task.document_id,
        source_path=task.source_path,
        page_number=task.page_number,
        text="",
        char_count=0,
        extraction_method=f"ocr:{task.ocr_tier.value}",
        rasterization_ms=0.0,
        ocr_ms=0.0,
        normalization_ms=0.0,
        worker_pid=os.getpid(),
        attempt=task.attempt,
        error_message=message,
    )


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000.0
