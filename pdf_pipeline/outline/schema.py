"""Schema types for document outline extraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceType = Literal["pdf_outline", "page_labels", "anchor_scan", "unresolved"]
SOURCE_TYPES: frozenset[str] = frozenset(
    {"pdf_outline", "page_labels", "anchor_scan", "unresolved"}
)


@dataclass(frozen=True)
class OutlineEntry:
    id: str
    title: str
    level: int
    parent_id: str | None
    start_pdf_page: int | None
    end_pdf_page: int | None
    printed_page: str | None
    confidence: float
    source: SourceType

    def __post_init__(self) -> None:
        if self.source not in SOURCE_TYPES:
            raise ValueError(f"unknown source: {self.source}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )


@dataclass(frozen=True)
class DocumentOutline:
    source_id: str
    version: int
    entries: list[OutlineEntry] = field(default_factory=list)
