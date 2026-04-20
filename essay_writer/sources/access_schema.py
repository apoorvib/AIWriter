from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pdf_pipeline.ocr import OcrTier


SourceUnitType = Literal["pdf_page", "section", "chunk"]
SourceLocatorType = Literal["pdf_pages", "section", "search", "chunk"]
OversizedRequestPolicy = Literal["reject", "cap"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceAccessConfig:
    max_research_rounds: int = 3
    max_source_packets: int = 40
    max_total_source_chars: int = 200_000
    max_pdf_pages_per_request: int = 80
    max_pdf_pages_total: int = 240
    max_chars_per_packet: int = 50_000
    oversized_request_policy: OversizedRequestPolicy = "reject"
    lazy_pdf_ocr_enabled: bool = True
    lazy_ocr_tier: OcrTier = OcrTier.SMALL
    lazy_ocr_dpi: int = 300
    lazy_ocr_languages: tuple[str, ...] = ("en",)

    @classmethod
    def from_env(cls) -> "SourceAccessConfig":
        return cls(
            max_research_rounds=_env_int("ESSAY_MAX_RESEARCH_ROUNDS", cls.max_research_rounds),
            max_source_packets=_env_int("ESSAY_MAX_SOURCE_PACKETS", cls.max_source_packets),
            max_total_source_chars=_env_int("ESSAY_MAX_TOTAL_SOURCE_CHARS", cls.max_total_source_chars),
            max_pdf_pages_per_request=_env_int(
                "ESSAY_MAX_PDF_PAGES_PER_REQUEST",
                cls.max_pdf_pages_per_request,
            ),
            max_pdf_pages_total=_env_int("ESSAY_MAX_PDF_PAGES_TOTAL", cls.max_pdf_pages_total),
            max_chars_per_packet=_env_int("ESSAY_MAX_CHARS_PER_PACKET", cls.max_chars_per_packet),
            oversized_request_policy=_env_policy("ESSAY_OVERSIZED_SOURCE_REQUEST_POLICY", "reject"),
            lazy_pdf_ocr_enabled=_env_bool("ESSAY_LAZY_PDF_OCR_ENABLED", cls.lazy_pdf_ocr_enabled),
            lazy_ocr_tier=OcrTier(os.environ.get("ESSAY_LAZY_OCR_TIER", cls.lazy_ocr_tier.value)),
            lazy_ocr_dpi=_env_int("ESSAY_LAZY_OCR_DPI", cls.lazy_ocr_dpi),
            lazy_ocr_languages=_env_languages("ESSAY_LAZY_OCR_LANGUAGES", cls.lazy_ocr_languages),
        )

    def __post_init__(self) -> None:
        for name, value in [
            ("max_research_rounds", self.max_research_rounds),
            ("max_source_packets", self.max_source_packets),
            ("max_total_source_chars", self.max_total_source_chars),
            ("max_pdf_pages_per_request", self.max_pdf_pages_per_request),
            ("max_pdf_pages_total", self.max_pdf_pages_total),
            ("max_chars_per_packet", self.max_chars_per_packet),
        ]:
            if value < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.oversized_request_policy not in {"reject", "cap"}:
            raise ValueError("oversized_request_policy must be 'reject' or 'cap'")
        if isinstance(self.lazy_ocr_tier, str):
            object.__setattr__(self, "lazy_ocr_tier", OcrTier(self.lazy_ocr_tier))
        if self.lazy_ocr_dpi < 72:
            raise ValueError("lazy_ocr_dpi must be >= 72")
        if not self.lazy_ocr_languages:
            raise ValueError("lazy_ocr_languages must contain at least one language")


@dataclass(frozen=True)
class SourceUnit:
    source_id: str
    unit_id: str
    unit_type: SourceUnitType
    title: str | None = None
    heading_path: list[str] = field(default_factory=list)
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    text: str = ""
    char_count: int = 0
    text_quality: str = "unknown"
    extraction_method: str = "unknown"
    summary: str | None = None
    preview: str = ""

    def __post_init__(self) -> None:
        if self.pdf_page_start is not None and self.pdf_page_start < 1:
            raise ValueError("pdf_page_start must be >= 1")
        if self.pdf_page_end is not None:
            if self.pdf_page_start is None or self.pdf_page_end < self.pdf_page_start:
                raise ValueError("invalid pdf page range")


@dataclass(frozen=True)
class SourceMap:
    source_id: str
    source_type: str
    units: list[SourceUnit]
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_context(self, *, max_units: int = 120, preview_chars: int = 220) -> str:
        units = self.units[:max_units]
        lines = [f"Source ID: {self.source_id}", f"Type: {self.source_type}", f"Units: {len(self.units)}"]
        if len(units) < len(self.units):
            lines.append(f"Showing first {len(units)} units.")
        for unit in units:
            label = unit.unit_id
            if unit.unit_type == "pdf_page":
                printed = f", printed={unit.printed_page_start}" if unit.printed_page_start else ""
                label = f"{unit.unit_id} | pdf_page={unit.pdf_page_start}{printed}"
            heading = " > ".join(unit.heading_path) or unit.title or ""
            preview = unit.preview
            if len(preview) > preview_chars:
                preview = preview[: preview_chars - 3].rstrip() + "..."
            lines.append(f"- {label} | {heading} | {unit.char_count} chars | {preview}")
        if self.warnings:
            lines.append("Warnings: " + "; ".join(self.warnings))
        return "\n".join(lines)


@dataclass(frozen=True)
class SourceLocator:
    source_id: str
    locator_type: SourceLocatorType
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    printed_page_label: str | None = None
    section_id: str | None = None
    query: str | None = None
    chunk_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SourceTextPacket:
    packet_id: str
    source_id: str
    locator: SourceLocator
    text: str
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    heading_path: list[str] = field(default_factory=list)
    extraction_method: str = "unknown"
    text_quality: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)


def locator_from_payload(payload: dict) -> SourceLocator:
    return SourceLocator(
        source_id=str(payload.get("source_id", "")).strip(),
        locator_type=str(payload.get("locator_type", "")).strip(),  # type: ignore[arg-type]
        pdf_page_start=_optional_int(payload.get("pdf_page_start")),
        pdf_page_end=_optional_int(payload.get("pdf_page_end")),
        printed_page_label=_optional_str(payload.get("printed_page_label")),
        section_id=_optional_str(payload.get("section_id")),
        query=_optional_str(payload.get("query")),
        chunk_id=_optional_str(payload.get("chunk_id")),
        reason=_optional_str(payload.get("reason")),
    )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    return int(value)


def _env_policy(name: str, default: OversizedRequestPolicy) -> OversizedRequestPolicy:
    value = os.environ.get(name)
    if not value:
        return default
    if value not in {"reject", "cap"}:
        raise ValueError(f"{name} must be 'reject' or 'cap'")
    return value  # type: ignore[return-value]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _env_languages(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    languages = tuple(part.strip() for part in value.split(",") if part.strip())
    return languages or default
