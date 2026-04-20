from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from essay_writer.sources.access_schema import (
    SourceAccessConfig,
    SourceLocator,
    SourceMap,
    SourceTextPacket,
    SourceUnit,
)
from essay_writer.sources.index import SQLiteChunkIndex
from essay_writer.sources.lazy_ocr import DefaultPdfPageOcrProvider, PdfPageOcrProvider
from essay_writer.sources.map import build_source_map
from essay_writer.sources.schema import SourceChunk, SourceDocument, SourcePage
from essay_writer.sources.storage import SourceStore


class SourceAccessService:
    def __init__(
        self,
        store: SourceStore,
        *,
        config: SourceAccessConfig | None = None,
        pdf_page_ocr_provider: PdfPageOcrProvider | None = None,
    ) -> None:
        self._store = store
        self._config = config or SourceAccessConfig()
        self._pdf_page_ocr_provider = pdf_page_ocr_provider

    @property
    def config(self) -> SourceAccessConfig:
        return self._config

    def get_source_map(self, source_id: str) -> SourceMap:
        return self._store.load_source_map(source_id)

    def resolve_locators(
        self,
        locators: list[SourceLocator],
        *,
        max_total_chars: int | None = None,
    ) -> list[SourceTextPacket]:
        max_total = max_total_chars or self._config.max_total_source_chars
        packets: list[SourceTextPacket] = []
        seen: set[str] = set()
        total_chars = 0
        total_pdf_pages = 0

        for locator in locators:
            if len(packets) >= self._config.max_source_packets:
                break
            resolved = self._resolve_one(locator)
            for packet in resolved:
                key = _packet_key(packet)
                if key in seen:
                    continue
                seen.add(key)
                page_count = _packet_pdf_page_count(packet)
                if total_pdf_pages + page_count > self._config.max_pdf_pages_total:
                    continue
                text = packet.text
                warnings = list(packet.warnings)
                if len(text) > self._config.max_chars_per_packet:
                    text = text[: self._config.max_chars_per_packet].rstrip()
                    warnings.append(
                        f"Packet text was truncated to {self._config.max_chars_per_packet} characters."
                    )
                if total_chars + len(text) > max_total:
                    continue
                packets.append(replace(packet, text=text, warnings=warnings))
                total_chars += len(text)
                total_pdf_pages += page_count
                if len(packets) >= self._config.max_source_packets:
                    break
        return packets

    def search_source(
        self,
        source_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[SourceLocator]:
        source = self._store.load_source(source_id)
        if not source.index_path:
            return []
        with SQLiteChunkIndex(source.index_path) as index:
            results = index.search(query, limit=limit)
        return [
            SourceLocator(
                source_id=result.source_id,
                locator_type="chunk",
                chunk_id=result.chunk_id,
                query=query,
                reason=f"Search result for: {query}",
            )
            for result in results
        ]

    def _resolve_one(self, locator: SourceLocator) -> list[SourceTextPacket]:
        if locator.locator_type == "pdf_pages":
            return [self._resolve_pdf_pages(locator)]
        if locator.locator_type == "section":
            return [self._resolve_section(locator)]
        if locator.locator_type == "chunk":
            return [self._resolve_chunk(locator)]
        if locator.locator_type == "search":
            if not locator.query:
                return [_warning_packet(locator, "Search locator is missing query.")]
            return self.resolve_locators(self.search_source(locator.source_id, locator.query))
        return [_warning_packet(locator, f"Unsupported locator_type={locator.locator_type}.")]

    def _resolve_pdf_pages(self, locator: SourceLocator) -> SourceTextPacket:
        source_map = self._store.load_source_map(locator.source_id)
        if source_map.source_type != "pdf":
            return _warning_packet(locator, "PDF page locator was used for a non-PDF source.")
        source = self._store.load_source(locator.source_id)
        start = locator.pdf_page_start
        end = locator.pdf_page_end or start
        if start is None and locator.printed_page_label:
            start = _pdf_page_for_printed_label(source_map, locator.printed_page_label)
            end = start
        if start is None or end is None:
            return _warning_packet(locator, "PDF page locator is missing physical pdf_page_start.")
        if start < 1 or end < start:
            return _warning_packet(locator, "PDF page locator has an invalid physical page range.")
        requested_count = end - start + 1
        if requested_count > self._config.max_pdf_pages_per_request:
            if self._config.oversized_request_policy == "reject":
                return _warning_packet(
                    locator,
                    f"Requested {requested_count} PDF pages; max_pdf_pages_per_request="
                    f"{self._config.max_pdf_pages_per_request}.",
            )
            end = start + self._config.max_pdf_pages_per_request - 1
        if source.page_count and end > source.page_count:
            return _warning_packet(
                locator,
                f"Requested physical PDF pages {start}-{end}, but source has {source.page_count} pages.",
            )
        lazy_warnings: list[str] = []
        source_map, lazy_warnings = self._ensure_requested_pdf_pages(source, source_map, start, end)
        units = [
            unit
            for unit in source_map.units
            if unit.unit_type == "pdf_page"
            and unit.pdf_page_start is not None
            and start <= unit.pdf_page_start <= end
        ]
        if not units:
            return _warning_packet(locator, f"No stored text found for PDF pages {start}-{end}.")
        requested_pages = set(range(start, end + 1))
        missing_unit_pages = sorted(requested_pages - {unit.pdf_page_start for unit in units})
        missing_text_pages = sorted(
            page
            for page in requested_pages
            if next((unit for unit in units if unit.pdf_page_start == page and unit.text.strip()), None) is None
        )
        warnings = lazy_warnings
        if missing_unit_pages:
            warnings.append(f"Missing stored PDF page units: {missing_unit_pages}.")
        if missing_text_pages:
            warnings.append(f"Missing readable text for physical PDF pages: {missing_text_pages}.")
        text_units = [unit for unit in units if unit.text.strip()]
        return SourceTextPacket(
            packet_id=f"{locator.source_id}-pdf-pages-{start:04d}-{end:04d}",
            source_id=locator.source_id,
            locator=replace(locator, pdf_page_start=start, pdf_page_end=end),
            text="\n\n".join(_unit_heading(unit) + unit.text for unit in text_units).strip(),
            pdf_page_start=start,
            pdf_page_end=end,
            printed_page_start=units[0].printed_page_start,
            printed_page_end=units[-1].printed_page_end,
            heading_path=[],
            extraction_method="+".join(sorted({unit.extraction_method for unit in units})),
            text_quality=_combined_quality(units),
            warnings=warnings,
        )

    def _resolve_section(self, locator: SourceLocator) -> SourceTextPacket:
        if not locator.section_id:
            return _warning_packet(locator, "Section locator is missing section_id.")
        source_map = self._store.load_source_map(locator.source_id)
        unit = next((item for item in source_map.units if item.unit_id == locator.section_id), None)
        if unit is None:
            return _warning_packet(locator, f"Section not found: {locator.section_id}.")
        return SourceTextPacket(
            packet_id=unit.unit_id,
            source_id=locator.source_id,
            locator=locator,
            text=unit.text,
            heading_path=unit.heading_path,
            extraction_method=unit.extraction_method,
            text_quality=unit.text_quality,
        )

    def _resolve_chunk(self, locator: SourceLocator) -> SourceTextPacket:
        if not locator.chunk_id:
            return _warning_packet(locator, "Chunk locator is missing chunk_id.")
        chunks = self._store.load_chunks(locator.source_id)
        chunk = next((item for item in chunks if item.id == locator.chunk_id), None)
        if chunk is None:
            return _warning_packet(locator, f"Chunk not found: {locator.chunk_id}.")
        return _packet_from_chunk(locator, chunk)

    def _ensure_requested_pdf_pages(
        self,
        source: SourceDocument,
        source_map: SourceMap,
        start: int,
        end: int,
    ) -> tuple[SourceMap, list[str]]:
        if not self._config.lazy_pdf_ocr_enabled:
            return source_map, []
        pages_to_ocr = _pages_requiring_ocr(source_map, start, end)
        if not pages_to_ocr:
            return source_map, []
        original_path = Path(source.original_path)
        if not original_path.exists():
            return source_map, [
                "Lazy OCR was requested for missing/low-quality PDF pages, but the stored original PDF was not found."
            ]
        provider = self._pdf_page_ocr_provider or DefaultPdfPageOcrProvider(
            ocr_tier=self._config.lazy_ocr_tier,
            dpi=self._config.lazy_ocr_dpi,
            languages=self._config.lazy_ocr_languages,
        )
        try:
            ocr_pages = provider.extract_pages(original_path, pages_to_ocr, source_id=source.id)
        except Exception as exc:  # pragma: no cover - runtime OCR dependencies vary by machine
            return source_map, [f"Lazy OCR failed for PDF pages {pages_to_ocr}: {exc}"]
        if not ocr_pages:
            return source_map, [f"Lazy OCR did not return readable text for PDF pages {pages_to_ocr}."]

        current_pages = self._store.load_pages(source.id)
        updated_pages, changed_pages = _merge_lazy_ocr_pages(current_pages, ocr_pages)
        if not changed_pages:
            return source_map, [f"Lazy OCR did not improve PDF pages {pages_to_ocr}."]

        updated_source = replace(
            source,
            char_count=sum(page.char_count for page in updated_pages),
            extraction_method=_page_extraction_method(updated_pages),
            text_quality=_document_text_quality(updated_pages),
        )
        updated_map = build_source_map(
            updated_source,
            updated_pages,
            printed_page_labels=_printed_page_labels(source_map),
        )
        self._store.save_text_artifacts(updated_source, updated_pages, updated_map)
        return updated_map, [f"Lazy OCR refreshed physical PDF pages: {changed_pages}."]


def _packet_from_chunk(locator: SourceLocator, chunk: SourceChunk) -> SourceTextPacket:
    return SourceTextPacket(
        packet_id=chunk.id,
        source_id=chunk.source_id,
        locator=locator,
        text=chunk.text,
        pdf_page_start=chunk.page_start,
        pdf_page_end=chunk.page_end,
        extraction_method="chunk",
        text_quality="readable" if chunk.char_count >= 300 else "partial",
    )


def _warning_packet(locator: SourceLocator, warning: str) -> SourceTextPacket:
    return SourceTextPacket(
        packet_id=f"{locator.source_id}-warning-{abs(hash((locator.locator_type, warning))) % 100000}",
        source_id=locator.source_id,
        locator=locator,
        text="",
        warnings=[warning],
    )


def _pdf_page_for_printed_label(source_map: SourceMap, printed: str) -> int | None:
    target = printed.strip().lower()
    for unit in source_map.units:
        if unit.printed_page_start and unit.printed_page_start.strip().lower() == target:
            return unit.pdf_page_start
    return None


def _unit_heading(unit: SourceUnit) -> str:
    if unit.pdf_page_start is None:
        return ""
    printed = f", printed page {unit.printed_page_start}" if unit.printed_page_start else ""
    return f"[PDF page {unit.pdf_page_start}{printed}]\n"


def _combined_quality(units: list[SourceUnit]) -> str:
    qualities = {unit.text_quality for unit in units}
    if "low" in qualities:
        return "low"
    if "partial" in qualities:
        return "partial"
    if "readable" in qualities:
        return "readable"
    return "unknown"


def _pages_requiring_ocr(source_map: SourceMap, start: int, end: int) -> list[int]:
    units_by_page = {
        unit.pdf_page_start: unit
        for unit in source_map.units
        if unit.unit_type == "pdf_page" and unit.pdf_page_start is not None
    }
    pages: list[int] = []
    for page_number in range(start, end + 1):
        unit = units_by_page.get(page_number)
        if unit is None or unit.text_quality in {"low", "partial", "unknown"}:
            pages.append(page_number)
    return pages


def _merge_lazy_ocr_pages(
    current_pages: list[SourcePage],
    ocr_pages: list[SourcePage],
) -> tuple[list[SourcePage], list[int]]:
    current_by_page = {page.page_number: page for page in current_pages}
    changed_pages: list[int] = []
    for ocr_page in ocr_pages:
        current = current_by_page.get(ocr_page.page_number)
        if not ocr_page.text.strip():
            continue
        if current is None or ocr_page.char_count > current.char_count:
            current_by_page[ocr_page.page_number] = ocr_page
            changed_pages.append(ocr_page.page_number)
    return sorted(current_by_page.values(), key=lambda item: item.page_number), sorted(changed_pages)


def _printed_page_labels(source_map: SourceMap) -> dict[int, str]:
    return {
        unit.pdf_page_start: unit.printed_page_start
        for unit in source_map.units
        if unit.unit_type == "pdf_page"
        and unit.pdf_page_start is not None
        and unit.printed_page_start
    }


def _page_extraction_method(pages: list[SourcePage]) -> str:
    methods = sorted({page.extraction_method for page in pages if page.extraction_method})
    if not methods:
        return "unknown"
    if len(methods) == 1:
        return methods[0]
    return "+".join(methods)


def _document_text_quality(pages: list[SourcePage]) -> str:
    if not pages:
        return "low"
    readable = sum(1 for page in pages if page.char_count >= 300)
    if readable / len(pages) >= 0.7:
        return "readable"
    if any(page.char_count > 0 for page in pages):
        return "partial"
    return "low"


def _packet_key(packet: SourceTextPacket) -> str:
    return "|".join(
        [
            packet.source_id,
            packet.packet_id,
            str(packet.pdf_page_start),
            str(packet.pdf_page_end),
            ",".join(packet.heading_path),
        ]
    )


def _packet_pdf_page_count(packet: SourceTextPacket) -> int:
    if packet.pdf_page_start is None or packet.pdf_page_end is None:
        return 0
    return packet.pdf_page_end - packet.pdf_page_start + 1
