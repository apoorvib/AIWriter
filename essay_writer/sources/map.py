from __future__ import annotations

import re

from essay_writer.sources.access_schema import SourceMap, SourceUnit
from essay_writer.sources.schema import SourceDocument, SourcePage


def build_source_map(
    source: SourceDocument,
    pages: list[SourcePage],
    *,
    printed_page_labels: dict[int, str] | None = None,
) -> SourceMap:
    if source.source_type == "pdf":
        return _pdf_source_map(source, pages, printed_page_labels or {})
    return _section_source_map(source, pages)


def _pdf_source_map(
    source: SourceDocument,
    pages: list[SourcePage],
    printed_page_labels: dict[int, str],
) -> SourceMap:
    units = [
        SourceUnit(
            source_id=source.id,
            unit_id=f"{source.id}-pdf-page-{page.page_number:04d}",
            unit_type="pdf_page",
            title=f"PDF page {page.page_number}",
            pdf_page_start=page.page_number,
            pdf_page_end=page.page_number,
            printed_page_start=printed_page_labels.get(page.page_number),
            printed_page_end=printed_page_labels.get(page.page_number),
            text=page.text,
            char_count=page.char_count,
            text_quality=_page_quality(page),
            extraction_method=page.extraction_method,
            summary=_compact(page.text, 260),
            preview=_compact(page.text, 220),
        )
        for page in pages
    ]
    warnings = []
    if not printed_page_labels:
        warnings.append("No PDF page-label metadata was available; use physical pdf_page numbers for retrieval.")
    return SourceMap(source_id=source.id, source_type=source.source_type, units=units, warnings=warnings)


def _section_source_map(source: SourceDocument, pages: list[SourcePage]) -> SourceMap:
    text = "\n\n".join(page.text.strip() for page in pages if page.text.strip())
    sections = _split_structured_sections(text, source.source_type)
    units = [
        SourceUnit(
            source_id=source.id,
            unit_id=f"{source.id}-sec-{idx:04d}",
            unit_type="section",
            title=" > ".join(section["heading_path"]) if section["heading_path"] else f"Section {idx}",
            heading_path=section["heading_path"],
            text=section["text"],
            char_count=len(section["text"]),
            text_quality="readable" if len(section["text"]) >= 80 else "low",
            extraction_method=pages[0].extraction_method if pages else source.extraction_method,
            summary=_compact(section["text"], 260),
            preview=_compact(section["text"], 220),
        )
        for idx, section in enumerate(sections, start=1)
        if section["text"].strip()
    ]
    warnings = []
    if not units and text:
        warnings.append("No section units were created even though source text exists.")
    return SourceMap(source_id=source.id, source_type=source.source_type, units=units, warnings=warnings)


def _split_structured_sections(text: str, source_type: str, *, target_chars: int = 8_000) -> list[dict]:
    if not text.strip():
        return []
    if source_type in {"md", "markdown"}:
        sections = _split_markdown_sections(text)
        if sections:
            return sections
    sections = _split_heading_like_sections(text)
    if sections:
        return _split_oversized_sections(sections, target_chars)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    sections = []
    current: list[str] = []
    current_chars = 0
    for paragraph in paragraphs:
        if current and current_chars + len(paragraph) > target_chars:
            sections.append({"heading_path": [], "text": "\n\n".join(current).strip()})
            current = []
            current_chars = 0
        current.append(paragraph)
        current_chars += len(paragraph)
    if current:
        sections.append({"heading_path": [], "text": "\n\n".join(current).strip()})
    return sections or [{"heading_path": [], "text": text.strip()}]


def _split_markdown_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    heading_stack: list[str] = []
    current_heading: list[str] = []
    current_lines: list[str] = []
    saw_heading = False

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            saw_heading = True
            if current_lines:
                sections.append({"heading_path": current_heading, "text": "\n".join(current_lines).strip()})
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_heading = list(heading_stack)
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append({"heading_path": current_heading, "text": "\n".join(current_lines).strip()})
    return [section for section in sections if section["text"]] if saw_heading else []


def _split_heading_like_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current_heading: list[str] = []
    current_lines: list[str] = []
    saw_heading = False

    for line in text.splitlines():
        stripped = line.strip()
        if _is_heading_like(stripped):
            saw_heading = True
            if current_lines:
                sections.append({"heading_path": current_heading, "text": "\n".join(current_lines).strip()})
            current_heading = [stripped]
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append({"heading_path": current_heading, "text": "\n".join(current_lines).strip()})
    return [section for section in sections if section["text"]] if saw_heading else []


def _split_oversized_sections(sections: list[dict], target_chars: int) -> list[dict]:
    result: list[dict] = []
    for section in sections:
        text = section["text"]
        if len(text) <= target_chars:
            result.append(section)
            continue
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        current: list[str] = []
        current_chars = 0
        part_number = 1
        for paragraph in paragraphs:
            if current and current_chars + len(paragraph) > target_chars:
                result.append(
                    {
                        "heading_path": [*section["heading_path"], f"Part {part_number}"],
                        "text": "\n\n".join(current).strip(),
                    }
                )
                part_number += 1
                current = []
                current_chars = 0
            current.append(paragraph)
            current_chars += len(paragraph)
        if current:
            result.append(
                {
                    "heading_path": [*section["heading_path"], f"Part {part_number}"]
                    if part_number > 1
                    else section["heading_path"],
                    "text": "\n\n".join(current).strip(),
                }
            )
    return result


def _is_heading_like(line: str) -> bool:
    if not line or len(line) > 120:
        return False
    if re.match(r"^[-=]{3,}$", line):
        return True
    if re.match(r"^(\d+(\.\d+)*|[A-Z])[\).:-]\s+\w+", line):
        return True
    words = line.split()
    if 2 <= len(words) <= 12 and (line.istitle() or line.isupper()):
        return True
    return False


def _page_quality(page: SourcePage) -> str:
    if page.char_count >= 300:
        return "readable"
    if page.char_count > 0:
        return "partial"
    return "low"


def _compact(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
