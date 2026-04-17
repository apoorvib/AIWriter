from enum import Enum


class ExtractionMode(str, Enum):
    TEXT_ONLY = "text_only"
    AUTO = "auto"
    OCR_ONLY = "ocr_only"
