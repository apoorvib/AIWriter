from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    char_count: int
    extraction_method: str


@dataclass(frozen=True)
class DocumentExtractionResult:
    source_path: str
    page_count: int
    pages: list[PageText]
