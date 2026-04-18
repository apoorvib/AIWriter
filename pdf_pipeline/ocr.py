from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OcrTier(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class OcrConfig:
    languages: tuple[str, ...] = ("en",)
    dpi: int = 300
    use_gpu: bool = False
    start_page: int = 1
    max_pages: int | None = None
