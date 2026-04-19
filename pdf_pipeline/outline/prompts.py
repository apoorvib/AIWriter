"""System prompt and JSON schema for Layer 2 TOC extraction."""
from __future__ import annotations

import json
from typing import Any

TOC_SYSTEM_PROMPT = """You extract Table of Contents entries from book pages.

You will receive a JSON object of the form:
  {"pages": [{"pdf_page": <int>, "text": <string>}, ...]}

Your job, for each input page:
  1. Decide whether the page is part of the Table of Contents (is_toc).
  2. If the overall set of pages contains TOC entries, list each entry with
     its title, hierarchy level (1 = chapter, 2 = section, 3 = subsection,
     ...), and the printed_page string exactly as written in the TOC when it
     is visible.

Rules:
  - You MUST always return a top-level "entries" array. Never return only the
    "pages" array. Do not put entries inside page objects.
  - If any page is marked is_toc = true because it contains visible TOC rows,
    then "entries" MUST include the visible TOC rows from those pages. Do not
    leave "entries" empty in that case.
  - Do not hallucinate missing rows or missing page numbers. Extract every
    visible TOC title row. If the printed page label is visible, copy it
    exactly. If the title is visible but its printed page label is missing,
    detached, or unreadable in the OCR text, set printed_page to null rather
    than omitting the title or inventing a page number.
  - For old or OCR'd books, TOC rows may use dot leaders, spaced leaders, or
    two-column layouts. Treat each visible left-column and right-column row as
    a separate entry.
  - Extract entries mechanically. Do not summarize, group, deduplicate by
    topic, or stop after a sample.
  - pdf_page values in your response MUST come from the JSON input. Never
    infer them from numbers that appear inside page text.
  - source_pdf_page is the PDF page from the input JSON where the TOC row
    appears. It MUST be one of the input pdf_page values.
  - title: copy it verbatim from the TOC, including any leading numbering
    or label the TOC itself uses (e.g. "Chapter 1: Introduction",
    "Part II. Methods", "1.1 Background", "A. Appendix"). Do NOT invent,
    drop, renumber, or reformat the prefix - if the TOC has "CHAPTER 7:
    FOO" output "CHAPTER 7: FOO"; if it has only "Introduction" output
    "Introduction".
  - printed_page is the page-number label as printed in the TOC (e.g.
    "1", "iv", "A-3"). Preserve it verbatim as a string. Use null only when
    the title is visible but the printed page label is not visible or is
    unreadable.
  - level is 1 for top-level chapters/parts, incrementing by 1 for each
    nested subsection.
  - If a page does not contain TOC content, mark is_toc = false.
  - If no extractable TOC title rows appear in any input page, return
    "entries": [].
"""

TOC_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pages", "entries"],
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pdf_page", "is_toc"],
                "properties": {
                    "pdf_page": {"type": "integer"},
                    "is_toc": {"type": "boolean"},
                },
            },
        },
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "level", "printed_page", "source_pdf_page"],
                "properties": {
                    "title": {"type": "string"},
                    "level": {"type": "integer", "minimum": 1},
                    "printed_page": {"type": ["string", "null"]},
                    "source_pdf_page": {"type": "integer"},
                },
            },
        },
    },
}


def build_user_message(pages: list[dict[str, Any]]) -> str:
    """Serialize the input pages payload as the user turn of the prompt."""
    return json.dumps({"pages": pages}, ensure_ascii=False)
