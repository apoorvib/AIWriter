"""Cheap heuristic to detect whether a page looks like part of a TOC."""
from __future__ import annotations

import re

_HEADING_PATTERN = re.compile(
    r"^\s*(table of contents|contents)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DOT_LEADER_PATTERN = re.compile(r"\.{3,}\s*\d+\s*$", re.MULTILINE)
_SHORT_LINE_NUM_PATTERN = re.compile(r"^\s*\S.{0,60}?\s+\d+\s*$", re.MULTILINE)


def looks_like_toc(text: str) -> bool:
    """Heuristically decide whether `text` looks like TOC content.

    Triggers on any of: a "Contents"/"Table of Contents" heading, three or
    more dot-leader lines, or ten or more short lines that end in a number.
    """
    if not text or not text.strip():
        return False

    if _HEADING_PATTERN.search(text):
        return True

    if len(_DOT_LEADER_PATTERN.findall(text)) >= 3:
        return True

    if len(_SHORT_LINE_NUM_PATTERN.findall(text)) >= 10:
        return True

    return False
