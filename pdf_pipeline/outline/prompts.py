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
     ...), and the printed_page string exactly as written in the TOC.

Rules:
  - pdf_page values in your response MUST come from the JSON input. Never
    infer them from numbers that appear inside page text.
  - title: copy it verbatim from the TOC, including any leading numbering
    or label the TOC itself uses (e.g. "Chapter 1: Introduction",
    "Part II. Methods", "1.1 Background", "A. Appendix"). Do NOT invent,
    drop, renumber, or reformat the prefix - if the TOC has "CHAPTER 7:
    FOO" output "CHAPTER 7: FOO"; if it has only "Introduction" output
    "Introduction".
  - printed_page is the page-number label as printed in the TOC (e.g.
    "1", "iv", "A-3"). Preserve it verbatim as a string.
  - level is 1 for top-level chapters/parts, incrementing by 1 for each
    nested subsection.
  - If a page does not contain TOC content, mark is_toc = false.
  - If no TOC entries appear in any input page, return "entries": [].
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
                "required": ["title", "level", "printed_page"],
                "properties": {
                    "title": {"type": "string"},
                    "level": {"type": "integer", "minimum": 1},
                    "printed_page": {"type": "string"},
                },
            },
        },
    },
}


def build_user_message(pages: list[dict[str, Any]]) -> str:
    """Serialize the input pages payload as the user turn of the prompt."""
    return json.dumps({"pages": pages}, ensure_ascii=False)
